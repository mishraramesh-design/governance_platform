"""Immutable snapshots of repository audit projections, addressable by original ID."""
import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

COLLECTIONS = ('findings', 'events', 'reports', 'repo_audits')


async def initialize(db):
    await db.repo_audit_history.create_index('id', unique=True)
    await db.repo_audit_versions.create_index('id', unique=True)


def record_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


async def snapshot_project(db, project):
    await initialize(db)
    version_id = uuid4().hex
    entries = []
    for collection in COLLECTIONS:
        async for record in db[collection].find({'project_id': project['id']}, {'_id': 0}):
            if len(entries) >= 10000:
                raise RuntimeError('Audit snapshot exceeds online migration limit; current records were not removed.')
            key = hashlib.sha256(f"{collection}:{record['id']}".encode()).hexdigest()
            digest = record_hash(record)
            existing = await db.repo_audit_history.find_one({'id': key}, {'sha256': 1})
            if existing and existing['sha256'] != digest:
                raise RuntimeError('An archived record changed; audit halted to preserve evidence.')
            await db.repo_audit_history.update_one({'id': key}, {'$setOnInsert': {
                'id': key, 'collection': collection, 'record_id': record['id'],
                'project_id': project['id'], 'version_id': version_id,
                'record': record, 'sha256': digest}}, upsert=True)
            entries.append({'collection': collection, 'record_id': record['id'], 'sha256': digest})
    manifest = {'id': version_id, 'project_id': project['id'], 'project': project,
                'archived_at': datetime.now(timezone.utc).isoformat(), 'records': entries,
                'snapshot_sha256': record_hash(entries)}
    await db.repo_audit_versions.insert_one(dict(manifest))
    return manifest


async def historical_record(db, collection, record_id):
    record = await db[collection].find_one({'id': record_id}, {'_id': 0})
    if record:
        return record
    archived = await db.repo_audit_history.find_one({'collection': collection, 'record_id': record_id}, {'_id': 0})
    if not archived:
        return None
    if record_hash(archived['record']) != archived['sha256']:
        raise RuntimeError('Archived evidence failed its content hash check.')
    return archived['record']
