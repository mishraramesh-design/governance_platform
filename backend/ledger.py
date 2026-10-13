"""Append-only, SHA-256 hash-chained ledger for a tamper-evident audit trail.

One chain per project plus one platform chain ("_global") for platform-wide events. Each
chain has its own contiguous seq and prev_hash. Appends are serialised in-process by a lock
and across processes by a unique index on (chain, seq) with retry, so the chain cannot fork.

Entry formats: v1 (legacy, no chain id in the hash) and v2 (chain id is part of the hash).
Legacy entries are migrated into the "_global" chain without changing their hashes.
"""
import json
import asyncio
import hashlib
import logging
from uuid import uuid4
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

logger = logging.getLogger(__name__)

GENESIS_HASH = "0" * 64
GLOBAL = "_global"

_append_lock = asyncio.Lock()

# payload types whose ref is a document id in another collection that knows its project
_REF_COLLECTION = {
    "finding": "findings", "report": "reports", "adjudication": "adjudications",
    "event": "events", "artifact": "artifacts", "edge_bundle": "edge_bundles",
}


def _core_v1(seq, prev_hash, payload_type, payload_ref, payload_summary, timestamp):
    return f"{seq}|{prev_hash}|{payload_type}|{payload_ref}|{json.dumps(payload_summary, sort_keys=True, default=str)}|{timestamp}"


def _core(entry, seq=None, prev_hash=None):
    seq = entry["seq"] if seq is None else seq
    prev_hash = entry["prev_hash"] if prev_hash is None else prev_hash
    base = _core_v1(seq, prev_hash, entry["payload_type"], entry["payload_ref"], entry["payload_summary"], entry["timestamp"])
    if entry.get("core_v") == 2:
        return f"{entry['chain']}|{base}"
    return base


async def ensure_ledger_indexes(db):
    """Idempotent: migrate legacy entries into the global chain and create indexes."""
    await db.ledger.update_many({"chain": {"$exists": False}}, {"$set": {"chain": GLOBAL}})
    try:
        await db.ledger.create_index([("chain", 1), ("seq", 1)], unique=True, name="ledger_chain_seq")
    except Exception as e:  # legacy forks must be repaired first via /ledger/rebuild
        logger.warning("ledger unique index not created: %s", e)
    await db.ledger.create_index([("payload_ref", 1)], name="ledger_ref")
    await db.ledger.create_index([("timestamp", -1)], name="ledger_ts")


async def infer_project(db, payload_type, payload_ref, summary, project_id=None):
    if project_id:
        return project_id
    if isinstance(summary, dict) and summary.get("project_id"):
        return summary["project_id"]
    if payload_type in ("project", "project_reaudit"):
        return payload_ref
    coll = _REF_COLLECTION.get(payload_type)
    if coll:
        doc = await db[coll].find_one({"id": payload_ref}, {"_id": 0, "project_id": 1})
        if doc and doc.get("project_id"):
            return doc["project_id"]
    if payload_type == "triage_decision" and isinstance(summary, dict) and summary.get("finding_id"):
        f = await db.findings.find_one({"id": summary["finding_id"]}, {"_id": 0, "project_id": 1})
        if f:
            return f.get("project_id")
    return None


async def append_to_ledger(db, payload_type: str, payload_ref: str, payload_summary: dict, project_id: str = None):
    chain = await infer_project(db, payload_type, payload_ref, payload_summary, project_id) or GLOBAL
    async with _append_lock:
        for _ in range(8):
            last = await db.ledger.find_one({"chain": chain}, {"_id": 0}, sort=[("seq", -1)])
            prev_hash = last["hash"] if last else GENESIS_HASH
            seq = (last["seq"] + 1) if last else 1
            entry = {
                "id": str(uuid4()), "chain": chain, "core_v": 2, "seq": seq, "prev_hash": prev_hash,
                "payload_type": payload_type, "payload_ref": payload_ref,
                "payload_summary": payload_summary, "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            entry["hash"] = hashlib.sha256(_core(entry).encode()).hexdigest()
            try:
                await db.ledger.insert_one(dict(entry))
                return entry
            except DuplicateKeyError:
                continue  # another process won this seq; re-read and retry
    raise RuntimeError("ledger append failed after retries")


async def chains(db):
    return sorted(await db.ledger.distinct("chain"))


async def verify_chain(db, chain: str):
    prev_hash, n = GENESIS_HASH, 0
    cursor = db.ledger.find({"chain": chain}, {"_id": 0}).sort("seq", 1)
    expected_seq = 1
    async for e in cursor:   # streamed; never loads the whole chain
        n += 1
        recomputed = hashlib.sha256(_core(e).encode()).hexdigest()
        if e["seq"] != expected_seq or recomputed != e["hash"] or e["prev_hash"] != prev_hash:
            return {"valid": False, "chain": chain, "broken_at_seq": e["seq"], "total_entries": n}
        prev_hash = e["hash"]
        expected_seq += 1
    return {"valid": True, "chain": chain, "total_entries": n, "last_hash": prev_hash}


async def verify_integrity(db, project_id: str = None):
    """With project_id: that project's chain. Without: every chain."""
    if project_id:
        return await verify_chain(db, project_id)
    results = [await verify_chain(db, c) for c in await chains(db)]
    bad = [r for r in results if not r["valid"]]
    total = sum(r["total_entries"] for r in results)
    if bad:
        b = bad[0]
        return {"valid": False, "broken_chain": b["chain"], "broken_at_seq": b["broken_at_seq"],
                "total_entries": total, "chains": len(results)}
    last = next((r["last_hash"] for r in results if r["chain"] == GLOBAL), None)
    return {"valid": True, "total_entries": total, "chains": len(results), "last_hash": last}


_cache = {"at": 0.0, "val": None}


async def verify_cached(db, ttl: float = 60.0):
    """Dashboard-friendly: full verification at most once per ttl seconds."""
    import time
    if _cache["val"] is None or time.time() - _cache["at"] > ttl:
        _cache["val"] = await verify_integrity(db)
        _cache["at"] = time.time()
    return _cache["val"]


async def rebuild_chain(db, chain: str = GLOBAL):
    """Repair a chain forked by the old concurrency bug. Keeps every entry; re-sequences and re-hashes."""
    async with _append_lock:
        entries = await db.ledger.find({"chain": chain}, {"_id": 0}).sort(
            [("seq", 1), ("timestamp", 1), ("id", 1)]).to_list(5_000_000)
        prev_hash, repaired = GENESIS_HASH, 0
        # two passes avoid transient unique-index collisions: park seqs high, then write final values
        for i, e in enumerate(entries, start=1):
            await db.ledger.update_one({"id": e["id"]}, {"$set": {"seq": 10_000_000 + i}})
        for i, e in enumerate(entries, start=1):
            new_hash = hashlib.sha256(_core(e, seq=i, prev_hash=prev_hash).encode()).hexdigest()
            if e["seq"] != i or e["prev_hash"] != prev_hash or e["hash"] != new_hash:
                repaired += 1
            await db.ledger.update_one({"id": e["id"]}, {"$set": {"seq": i, "prev_hash": prev_hash, "hash": new_hash}})
            prev_hash = new_hash
    return {"rebuilt": True, "chain": chain, "total_entries": len(entries), "entries_rewritten": repaired, "last_hash": prev_hash}
