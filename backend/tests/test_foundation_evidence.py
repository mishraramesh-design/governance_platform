import os
os.environ.setdefault('MONGO_URL','mongodb://127.0.0.1:27017')
os.environ.setdefault('DB_NAME','phase1_unit')
import asyncio, hashlib, json, unittest
from copy import deepcopy
from uuid import uuid4
from unittest.mock import AsyncMock, patch
from pathlib import Path
from types import SimpleNamespace
import ledger, audit_history, repo_ingest, auth
from tool_adapters import _run
from phase1_fakes import Database


def legacy_entry(ref):
    item={'id':ref,'seq':1,'prev_hash':ledger.GENESIS_HASH,'payload_type':'old','payload_ref':ref,'payload_summary':{},'timestamp':'2026-10-13T00:00:00+00:00'}
    item['hash']=hashlib.sha256(ledger._core_string(1,item['prev_hash'],'old',ref,{},item['timestamp']).encode()).hexdigest()
    return item


class LedgerEpochTests(unittest.IsolatedAsyncioTestCase):
    async def test_forked_legacy_records_unchanged_and_active_epoch_valid(self):
        db=Database()
        await db.ledger.insert_many([legacy_entry('a'),legacy_entry('b')])
        original=deepcopy(db.ledger.rows)
        await ledger.initialize(db)
        await ledger.append_to_ledger(db,'QA','test',{'actor':'fixture'})
        status=await ledger.verify_integrity(db)
        self.assertFalse(status['valid']);self.assertFalse(status['legacy']['valid'])
        self.assertTrue(status['active_chain']['valid']);self.assertTrue(status['legacy_snapshot_matches'])
        self.assertEqual(db.ledger.rows[:2],original)

    async def test_concurrent_unique_insert_retries_form_one_chain(self):
        db=Database();await ledger.initialize(db)
        await asyncio.gather(*(ledger._insert(db,'QA',str(i),{}) for i in range(25)))
        result=await ledger.verify_integrity(db)
        self.assertTrue(result['valid']);self.assertEqual(result['active_chain']['total_entries'],26)

    async def test_migration_is_idempotent_and_later_legacy_change_detected(self):
        db=Database();await db.ledger.insert_one(legacy_entry('a'))
        await asyncio.gather(ledger.initialize(db),ledger.initialize(db))
        self.assertEqual(sum(r.get('chain_id')=='v2' for r in db.ledger.rows),1)
        db.ledger.rows[0]['payload_summary']={'changed':True}
        result=await ledger.verify_integrity(db)
        self.assertFalse(result['valid']);self.assertFalse(result['legacy_snapshot_matches'])

    async def test_acknowledgment_never_turns_broken_history_green(self):
        db=Database();await db.ledger.insert_many([legacy_entry('a'),legacy_entry('b')])
        await ledger.acknowledge_legacy(db,'reviewer','Reviewed original evidence and documented the historical fork.')
        status=await ledger.verify_integrity(db)
        self.assertTrue(status['historical_review_acknowledged']);self.assertFalse(status['valid'])
        self.assertTrue(status['active_chain']['valid'])
        with self.assertRaises(ValueError):await ledger.rebuild_chain(db)


class AuditHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_old_record_ids_survive_projection_replacement(self):
        db=Database();project={'id':'p','name':'fixture'}
        old={'id':'old-report','project_id':'p','title':'Original report'}
        await db.reports.insert_one(old)
        snapshot=await audit_history.snapshot_project(db,project)
        await db.reports.delete_many({'project_id':'p'})
        self.assertEqual(await audit_history.historical_record(db,'reports','old-report'),old)
        self.assertEqual(snapshot['records'][0]['sha256'],audit_history.record_hash(old))

    async def test_archived_content_hash_mismatch_is_rejected(self):
        db=Database();await db.reports.insert_one({'id':'r','project_id':'p','title':'before'})
        await audit_history.snapshot_project(db,{'id':'p'})
        await db.reports.delete_many({})
        db.repo_audit_history.rows[0]['record']['title']='tampered'
        with self.assertRaises(RuntimeError):await audit_history.historical_record(db,'reports','r')

    async def test_repository_pipeline_retains_tool_results_and_previous_report(self):
        db=Database()
        project={'id':'p','name':'fixture','repo_url':'https://github.com/owner/fixture','source':'github_live','integrity_tier':'T2'}
        await db.projects.insert_one(project)
        await db.reports.insert_one({'id':'old-report','project_id':'p','title':'Original'})
        tools=[{'tool_id':'semgrep-ce','name':'Semgrep CE','version':'1.2.3','status':'completed_with_findings',
                'output_sha256':'a'*64,'finding_count':1,'findings':[{'rule_id':'unsafe-call','path':'app.py','line':1,'severity':'HIGH','summary':'Review rule'}]},
               {'tool_id':'trivy','name':'Trivy','status':'timed_out','findings':[]}]
        scan={'profile':{'languages':{'Python':1},'frameworks':[],'code_files_scanned':1,'approx_loc':2,'spec':{}},'scanned':[],'tool_assessments':tools}
        async def report(*args):
            result={'id':uuid4().hex,'project_id':'p','title':'New report'}
            await db.reports.insert_one(result);return result
        with (patch.object(repo_ingest,'_clone_and_scan',return_value=scan), patch.object(repo_ingest,'get_project_key',AsyncMock(return_value=b'fixture')),
             patch.object(repo_ingest.engine,'generate_author_report',report), patch.object(repo_ingest.engine,'generate_team_lead_report',report),
             patch.object(repo_ingest.engine,'compute_gate_status',AsyncMock(return_value=[]))):
            result=await repo_ingest._ingest_repo(db,project['repo_url'])
        self.assertEqual(result['tool_assessments'],tools)
        self.assertEqual(result['audit']['tool_assessments'],tools)
        external=[r for r in db.findings.rows if r.get('tool_id')=='semgrep-ce']
        self.assertEqual(len(external),1);self.assertEqual(external[0]['level2_status'],'not_independently_reviewed')
        self.assertEqual((await audit_history.historical_record(db,'reports','old-report'))['title'],'Original')
        self.assertTrue(db.repo_audit_versions.rows)


class ToolResultTests(unittest.TestCase):
    def test_tool_errors_do_not_become_completed_even_with_findings(self):
        output=json.dumps({'results':[{'check_id':'qa','extra':{'message':'password=QA_SECRET'},'path':'a.py'}],'errors':[{'type':'parse'}]})
        with patch('tool_adapters.subprocess.run',return_value=SimpleNamespace(returncode=2,stdout=output,stderr='')):
            result=_run('semgrep-ce',['semgrep'],Path.cwd())
        self.assertEqual(result['status'],'tool_error');self.assertEqual(result['finding_count'],1)
        self.assertNotIn('QA_SECRET',json.dumps(result))

    def test_empty_or_invalid_tool_output_is_not_a_clean_pass(self):
        for output in ('', '{}', 'not json'):
            with patch('tool_adapters.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=output,stderr='')):
                self.assertEqual(_run('semgrep-ce',['semgrep'],Path.cwd())['status'],'tool_error')


@unittest.skipUnless(os.environ.get('MONGO_TEST_URL'),'Real MongoDB integration enabled in CI')
class MongoEpochIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from motor.motor_asyncio import AsyncIOMotorClient
        self.client=AsyncIOMotorClient(os.environ['MONGO_TEST_URL'],serverSelectionTimeoutMS=5000)
        self.name='governance_phase1_'+uuid4().hex
        self.db=self.client[self.name]
    async def asyncTearDown(self):
        await self.client.drop_database(self.name);self.client.close()
    async def test_unique_index_handles_concurrent_writers_and_legacy_duplicates(self):
        await self.db.ledger.insert_many([legacy_entry('a'),legacy_entry('b')])
        await ledger.initialize(self.db)
        await asyncio.gather(*(ledger._insert(self.db,'CI',str(i),{}) for i in range(20)))
        result=await ledger.verify_integrity(self.db)
        self.assertTrue(result['active_chain']['valid']);self.assertFalse(result['legacy']['valid'])
        self.assertTrue(result['legacy_snapshot_matches'])
