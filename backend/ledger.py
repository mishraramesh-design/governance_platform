"""Append-only, SHA-256 hash-chained ledger for tamper-evident audit trail."""
import json
import asyncio
import hashlib
from uuid import uuid4
from datetime import datetime, timezone

GENESIS_HASH = "0" * 64

# Serialises the read-last-seq -> compute-hash -> insert critical section so that
# concurrent appends can never fork the chain with duplicate seq numbers.
# (Single-process async app -> an in-process lock is sufficient and correct.)
_append_lock = asyncio.Lock()


def _core_string(seq, prev_hash, payload_type, payload_ref, payload_summary, timestamp):
    return f"{seq}|{prev_hash}|{payload_type}|{payload_ref}|{json.dumps(payload_summary, sort_keys=True, default=str)}|{timestamp}"


async def append_to_ledger(db, payload_type: str, payload_ref: str, payload_summary: dict):
    async with _append_lock:
        last = await db.ledger.find_one({}, {"_id": 0}, sort=[("seq", -1)])
        prev_hash = last["hash"] if last else GENESIS_HASH
        seq = (last["seq"] + 1) if last else 1
        timestamp = datetime.now(timezone.utc).isoformat()
        core = _core_string(seq, prev_hash, payload_type, payload_ref, payload_summary, timestamp)
        entry_hash = hashlib.sha256(core.encode()).hexdigest()
        entry = {
            "id": str(uuid4()),
            "seq": seq,
            "prev_hash": prev_hash,
            "hash": entry_hash,
            "payload_type": payload_type,
            "payload_ref": payload_ref,
            "payload_summary": payload_summary,
            "timestamp": timestamp,
        }
        await db.ledger.insert_one(entry)
    entry.pop("_id", None)
    return entry


async def rebuild_chain(db):
    """Repair a chain that was previously forked by the concurrency bug.

    Keeps every existing entry (nothing is dropped), orders them deterministically
    by (original seq, timestamp, id), then re-assigns contiguous seq numbers and
    recomputes prev_hash/hash so verify_integrity passes again. Returns a summary.
    """
    async with _append_lock:
        entries = await db.ledger.find({}, {"_id": 0}).sort(
            [("seq", 1), ("timestamp", 1), ("id", 1)]).to_list(1000000)
        prev_hash = GENESIS_HASH
        repaired = 0
        for i, e in enumerate(entries, start=1):
            core = _core_string(i, prev_hash, e["payload_type"], e["payload_ref"],
                                 e["payload_summary"], e["timestamp"])
            new_hash = hashlib.sha256(core.encode()).hexdigest()
            if e["seq"] != i or e["prev_hash"] != prev_hash or e["hash"] != new_hash:
                await db.ledger.update_one(
                    {"id": e["id"]},
                    {"$set": {"seq": i, "prev_hash": prev_hash, "hash": new_hash}})
                repaired += 1
            prev_hash = new_hash
    return {"rebuilt": True, "total_entries": len(entries), "entries_rewritten": repaired,
            "last_hash": prev_hash}


async def verify_integrity(db):
    entries = await db.ledger.find({}, {"_id": 0}).sort("seq", 1).to_list(200000)
    prev_hash = GENESIS_HASH
    for e in entries:
        core = _core_string(e["seq"], prev_hash, e["payload_type"], e["payload_ref"], e["payload_summary"], e["timestamp"])
        recomputed = hashlib.sha256(core.encode()).hexdigest()
        if recomputed != e["hash"] or e["prev_hash"] != prev_hash:
            return {"valid": False, "broken_at_seq": e["seq"], "total_entries": len(entries)}
        prev_hash = e["hash"]
    return {"valid": True, "total_entries": len(entries), "last_hash": prev_hash}
