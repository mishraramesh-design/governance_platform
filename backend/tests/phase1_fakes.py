"""Small async collection fixture. Real unique-index tests also run in CI MongoDB."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4
from pymongo.errors import DuplicateKeyError


def matches(row, query):
    for key, wanted in query.items():
        if key == '$or':
            if not any(matches(row, part) for part in wanted): return False
            continue
        actual = row.get(key)
        if isinstance(wanted, dict):
            for op, value in wanted.items():
                if op == '$ne' and actual == value: return False
                if op == '$in' and actual not in value: return False
                if op == '$nin' and actual in value: return False
                if op == '$lt' and not (actual is not None and actual < value): return False
                if op == '$gt' and not (actual is not None and actual > value): return False
                if op == '$exists' and (key in row) != value: return False
        elif actual != wanted: return False
    return True


class Cursor:
    def __init__(self, rows): self.rows = deepcopy(rows)
    def sort(self, key, direction=1):
        fields = key if isinstance(key, list) else [(key, direction)]
        for field, order in reversed(fields): self.rows.sort(key=lambda r: r.get(field, ''), reverse=order < 0)
        return self
    async def to_list(self, length): return deepcopy(self.rows[:length])
    def __aiter__(self): self.iterator = iter(self.rows); return self
    async def __anext__(self):
        try: return deepcopy(next(self.iterator))
        except StopIteration: raise StopAsyncIteration


class Collection:
    def __init__(self): self.rows = []; self.indexes = []
    async def create_index(self, keys, **options):
        if options.get('unique'):
            self.indexes.append((keys if isinstance(keys, list) else [(keys, 1)], options.get('partialFilterExpression', {})))
    def find(self, query=None, projection=None):
        return Cursor([{k: deepcopy(v) for k, v in r.items() if k != '_id'} for r in self.rows if matches(r, query or {})])
    async def find_one(self, query=None, projection=None, sort=None):
        await asyncio.sleep(0)
        cursor = self.find(query, projection)
        if sort: cursor.sort(sort)
        rows = await cursor.to_list(1)
        return rows[0] if rows else None
    async def insert_one(self, value):
        await asyncio.sleep(0)
        value = deepcopy(value); value.setdefault('_id', uuid4().hex)
        for row in self.rows:
            if row['_id'] == value['_id']: raise DuplicateKeyError('duplicate _id')
            for keys, partial in self.indexes:
                if matches(value, partial) and matches(row, partial) and all(row.get(k) == value.get(k) for k, _ in keys):
                    raise DuplicateKeyError('duplicate indexed value')
        self.rows.append(value)
        return SimpleNamespace(inserted_id=value['_id'])
    async def insert_many(self, values):
        for value in values: await self.insert_one(value)
    async def count_documents(self, query): return sum(matches(row, query) for row in self.rows)
    async def update_one(self, query, update, upsert=False):
        row = next((r for r in self.rows if matches(r, query)), None)
        if row is None:
            if not upsert: return SimpleNamespace(modified_count=0, matched_count=0)
            row = {k: v for k, v in query.items() if not k.startswith('$') and not isinstance(v, dict)}
            row.update(deepcopy(update.get('$setOnInsert', {})))
            row.update(deepcopy(update.get('$set', {})))
            for key, value in update.get('$addToSet', {}).items(): row[key] = [value]
            await self.insert_one(row)
        else:
            row.update(deepcopy(update.get('$set', {})))
            for key, value in update.get('$inc', {}).items(): row[key] = row.get(key, 0) + value
            for key, value in update.get('$addToSet', {}).items():
                if value not in row.setdefault(key, []): row[key].append(value)
        return SimpleNamespace(modified_count=1, matched_count=1)
    async def update_many(self, query, update):
        for row in list(self.rows):
            if matches(row, query): await self.update_one({'_id': row['_id']}, update)
    async def find_one_and_update(self, query, update, **options):
        await self.update_one(query, update, options.get('upsert', False))
        return await self.find_one({k: v for k,v in query.items() if not k.startswith('$')})
    async def delete_many(self, query): self.rows = [row for row in self.rows if not matches(row, query)]
    async def delete_one(self, query):
        row = next((r for r in self.rows if matches(r, query)), None)
        if row: self.rows.remove(row)


class Database:
    def __init__(self): self.collections = {}
    def __getitem__(self, key): return self.collections.setdefault(key, Collection())
    def __getattr__(self, key): return self[key]
