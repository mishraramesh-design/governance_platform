import asyncio
import io
import json
import logging
import os
import unittest
from unittest.mock import AsyncMock, patch
from pymongo.errors import DuplicateKeyError
os.environ.setdefault('MONGO_URL', 'mongodb://127.0.0.1:27017')
os.environ.setdefault('DB_NAME', 'diagnostic_unit')
import ledger
from safe_logging import SafeRedactionFilter, AllowListJsonFormatter
from phase1_fakes import Database
from routers import testing_workspace as ws


class FailureDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_unrelated_unique_key_is_not_retried_as_sequence_contention(self):
        db = Database()
        await ledger.initialize(db)
        conflict = DuplicateKeyError('secret-in-error-must-not-be-logged', details={
            'keyPattern': {'id': 1}, 'keyValue': {'id': 'SECRET'}})
        with patch.object(db.ledger, 'insert_one', AsyncMock(side_effect=conflict)) as insert:
            with self.assertRaises(ledger.LedgerWriteError) as caught:
                await ledger.append_to_ledger(db, 'fixture', 'ref', {})
        self.assertEqual(insert.await_count, 1)
        self.assertNotIn('SECRET', str(caught.exception))

    async def test_failed_plan_approval_restores_review_and_never_marks_approved(self):
        db = Database()
        record = {'id': 'session', 'owner_id': 'owner', 'status': 'plan_review',
                  'approved_plan_hash': None, 'sources': [{'id': 'R1'}]}
        await db.testing_sessions.insert_one(record)
        request = ws.ApprovedPlan.model_validate({'plan': {'cases': [{'id': 'T1', 'title': 'Check heading',
            'source_ids': ['R1'], 'steps': ['Read heading'], 'expected': 'Heading shown'}]}})
        with (patch.object(ws, 'db', db), patch.object(ws, 'owned', AsyncMock(return_value=record)),
              patch.object(ws, 'audit', AsyncMock(side_effect=ledger.LedgerWriteError('Fixture storage failure')))):
            with self.assertRaises(ledger.LedgerWriteError):
                await ws.approve_plan('session', request, {'id': 'owner'})
        saved = await db.testing_sessions.find_one({'id': 'session'})
        self.assertEqual(saved['status'], 'plan_review')
        self.assertIsNone(saved['approved_plan_hash'])

    def test_exception_metadata_keeps_locations_without_values_or_source(self):
        secret = 'QA_PRIVATE_EXCEPTION_VALUE'
        try:
            raise ValueError(secret)
        except ValueError:
            import sys
            record = logging.LogRecord('fixture', logging.ERROR, __file__, 1, 'Operation failed', (), sys.exc_info())
        record.safe_exception = {'spoofed': secret}
        SafeRedactionFilter().filter(record)
        value = AllowListJsonFormatter().format(record)
        parsed = json.loads(value)
        self.assertEqual(parsed['exception']['type'], 'ValueError')
        self.assertTrue(parsed['exception']['frames'])
        self.assertNotIn(secret, value)
        self.assertNotIn('C:', value)
