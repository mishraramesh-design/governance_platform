"""Append-only, SHA-256 hash-chained ledger for tamper-evident audit trail."""
import json
import hashlib
from uuid import uuid4
from datetime import datetime, timezone

GENESIS_HASH = "0" * 64


def _core_string(seq, prev_hash, payload_type, payload_ref, payload_summary, timestamp):
    return f"{seq}|{prev_hash}|{payload_type}|{payload_ref}|{json.dumps(payload_summary, sort_keys=True, default=str)}|{timestamp}"


async def append_to_ledger(db, payload_type: str, payload_ref: str, payload_summary: dict):
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
