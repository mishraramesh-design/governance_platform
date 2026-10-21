"""Immutable ledger epochs; original legacy records/hashes are never rewritten.

An atomic MongoDB unique insert serializes v2 sequences across processes.
Contending writers reread the winning tail. A crash cannot reserve a sequence
without its record. Legacy failures remain visible even after acknowledgment.
"""
import json
import asyncio
import hashlib
from uuid import uuid4
from datetime import datetime, timezone
from pymongo.errors import DuplicateKeyError

GENESIS_HASH = '0' * 64
CHAIN = 'v2'
MAX_ENTRIES = 200000
_append_lock = asyncio.Lock()


def _core_string(seq, prev_hash, payload_type, payload_ref, payload_summary, timestamp, chain_id=None):
    value = f'{seq}|{prev_hash}|{payload_type}|{payload_ref}|{json.dumps(payload_summary, sort_keys=True, default=str)}|{timestamp}'
    return f'{chain_id}|{value}' if chain_id else value


def _digest(entries):
    ordered = sorted(entries, key=lambda e: (str(e.get('seq', '')), str(e.get('timestamp', '')), str(e.get('id', ''))))
    return hashlib.sha256(json.dumps(ordered, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def _verify(entries, chain_id=None):
    prev = GENESIS_HASH
    for expected_seq, item in enumerate(entries, 1):
        required = {'seq', 'prev_hash', 'payload_type', 'payload_ref', 'payload_summary', 'timestamp', 'hash'}
        if not required.issubset(item):
            return {'valid': False, 'broken_at_seq': item.get('seq', expected_seq),
                    'total_entries': len(entries), 'error': 'malformed_entry'}
        core = _core_string(item['seq'], item['prev_hash'], item['payload_type'], item['payload_ref'],
                            item['payload_summary'], item['timestamp'], chain_id)
        if item['seq'] != expected_seq or item['prev_hash'] != prev or hashlib.sha256(core.encode()).hexdigest() != item['hash']:
            return {'valid': False, 'broken_at_seq': item['seq'], 'total_entries': len(entries)}
        prev = item['hash']
    return {'valid': True, 'total_entries': len(entries), 'last_hash': prev}


async def _index(db):
    await db.ledger.create_index([('chain_id', 1), ('seq', 1)], unique=True,
        partialFilterExpression={'chain_id': CHAIN}, name='ledger_v2_sequence_unique')


async def _insert(db, payload_type, payload_ref, summary, only_if_empty=False):
    for _ in range(50):
        last = await db.ledger.find_one({'chain_id': CHAIN}, {'_id': 0}, sort=[('seq', -1)])
        if only_if_empty and last:
            return last
        seq, prev = (last['seq'] + 1, last['hash']) if last else (1, GENESIS_HASH)
        timestamp = datetime.now(timezone.utc).isoformat()
        core = _core_string(seq, prev, payload_type, payload_ref, summary, timestamp, CHAIN)
        entry = {'id': str(uuid4()), 'chain_id': CHAIN, 'seq': seq, 'prev_hash': prev,
                 'hash': hashlib.sha256(core.encode()).hexdigest(), 'payload_type': payload_type,
                 'payload_ref': payload_ref, 'payload_summary': summary, 'timestamp': timestamp}
        try:
            await db.ledger.insert_one(dict(entry))
            return entry
        except DuplicateKeyError:
            await asyncio.sleep(0)
    raise RuntimeError('Ledger append contention; event was not silently accepted.')


async def initialize(db):
    await _index(db)
    if await db.ledger.find_one({'chain_id': CHAIN}, {'id': 1}):
        return
    legacy = await db.ledger.find({'chain_id': {'$ne': CHAIN}}, {'_id': 0}).sort('seq', 1).to_list(MAX_ENTRIES + 1)
    if len(legacy) > MAX_ENTRIES:
        raise RuntimeError('Legacy ledger exceeds migration limit; use an offline reviewed migration.')
    await _insert(db, 'ledger_epoch_started', CHAIN, {
        'legacy_snapshot_sha256': _digest(legacy), 'legacy_count': len(legacy),
        'legacy_integrity': _verify(legacy),
        'migration': 'Original records and hashes retained without modification.'}, only_if_empty=True)


async def append_to_ledger(db, payload_type, payload_ref, payload_summary):
    async with _append_lock:
        await initialize(db)
        return await _insert(db, payload_type, payload_ref, payload_summary)


async def rebuild_chain(db):
    raise ValueError('In-place rebuilding is disabled. Record a reviewed baseline acknowledgment instead.')


async def acknowledge_legacy(db, actor, reason):
    await initialize(db)
    status = await verify_integrity(db)
    if not status.get('legacy_snapshot_matches') or not status.get('active_chain', {}).get('valid'):
        raise ValueError('Investigate snapshot mismatch or active-chain failure before acknowledgment.')
    return await append_to_ledger(db, 'legacy_review_acknowledged', CHAIN, {
        'actor_user_id': actor, 'reason': reason, 'legacy_snapshot_sha256': status['legacy_snapshot_sha256'],
        'legacy_integrity': status['legacy'], 'note': 'Acknowledgment does not make broken historical evidence valid.'})


async def verify_integrity(db):
    entries = await db.ledger.find({}, {'_id': 0}).sort('seq', 1).to_list(MAX_ENTRIES + 1)
    if len(entries) > MAX_ENTRIES:
        return {'valid': False, 'total_entries': len(entries), 'error': 'verification_limit_exceeded'}
    legacy = [entry for entry in entries if entry.get('chain_id') != CHAIN]
    active = [entry for entry in entries if entry.get('chain_id') == CHAIN]
    old_status, new_status = _verify(legacy), _verify(active, CHAIN)
    digest = _digest(legacy)
    manifest = active[0].get('payload_summary', {}) if active and active[0].get('payload_type') == 'ledger_epoch_started' else {}
    if not isinstance(manifest, dict):
        manifest = {}
    matches = manifest.get('legacy_snapshot_sha256') == digest if active else True
    valid = old_status['valid'] and new_status['valid'] and matches
    return {'valid': valid, 'total_entries': len(entries), 'legacy': old_status, 'active_chain': new_status,
            'active_chain_id': CHAIN, 'legacy_snapshot_sha256': digest, 'legacy_snapshot_matches': matches,
            'historical_review_acknowledged': any(e.get('payload_type') == 'legacy_review_acknowledged' for e in active),
            'broken_at_seq': old_status.get('broken_at_seq', new_status.get('broken_at_seq')),
            'last_hash': new_status.get('last_hash', old_status.get('last_hash')),
            'note': 'Legacy and v2 integrity are separate. Baseline acknowledgment never erases historical failure.'}
