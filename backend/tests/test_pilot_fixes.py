"""Regressions from the AuctionHub pilot. No live provider or target calls."""
import json
import ssl
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import gateway
import httpx
from engine import deterministic_report_summary
from routers import studio
from routers.reports import report_narrative


class PilotFixTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cfg = {'zero_llm_mode': False, 'max_llm_calls_per_run': 12,
                    'sovereignty': {'T1': True, 'T2': False},
                    'capability_profiles': {'maker': {'provider': 'openai', 'model': 'test-model',
                                                     'api_key': 'synthetic-key'}}}
        self.db = SimpleNamespace(projects=SimpleNamespace(find_one=AsyncMock(return_value={'tier': 'T2'})),
                                  llm_run_budgets=SimpleNamespace(find_one=AsyncMock(return_value=None)))

    async def check(self, **kw):
        with patch.object(gateway, 'get_config', AsyncMock(return_value=self.cfg)):
            return await gateway.workspace_readiness(self.db, project_id='p1', **kw)

    async def test_cloud_consent_is_required_and_keys_are_not_returned(self):
        result = await self.check()
        self.assertEqual(result['mode'], 'cloud-consent-required')
        self.assertNotIn('synthetic-key', json.dumps(result))

    async def test_actual_project_tier_cannot_be_bypassed_by_cloud_consent(self):
        self.db.projects.find_one.return_value = {'tier': 'T1'}
        self.assertEqual((await self.check(allow_cloud=True))['mode'], 'sovereignty-blocked')

    async def test_ready_key_and_consent_allow_agent_dispatch(self):
        result = await self.check(allow_cloud=True)
        self.assertTrue(result['ready'])
        self.assertEqual(result['limit'], 12)

    async def test_missing_key_and_exhausted_budget_are_actionable(self):
        self.cfg['capability_profiles']['maker']['api_key'] = ''
        with patch.dict(gateway.PROVIDER_API_KEYS, {'openai': None}):
            self.assertIn('API key', (await self.check(allow_cloud=True))['reason'])
        self.db.llm_run_budgets.find_one.return_value = {'calls_reserved': 12}
        self.assertEqual((await self.check(allow_cloud=True, run_id='s'))['mode'], 'budget-exhausted')

    async def test_openai_transport_omits_model_specific_sampling_parameters(self):
        captured = []
        contexts = []
        def respond(request):
            captured.append(json.loads(request.content))
            return httpx.Response(200, json={'choices': [{'message': {'content': '{"ready":true}'}}]})
        real_client = httpx.AsyncClient
        def make_client(**kw):
            contexts.append(kw['verify'])
            return real_client(transport=httpx.MockTransport(respond), **kw)
        with patch.object(gateway.httpx, 'AsyncClient', side_effect=make_client):
            text = await gateway._run_llm('JSON only', 'synthetic', self.cfg['capability_profiles']['maker'], 'synthetic', 'probe')
        self.assertEqual(json.loads(text), {'ready': True})
        self.assertNotIn('temperature', captured[0])
        self.assertTrue(contexts[0].check_hostname)
        self.assertEqual(contexts[0].verify_mode, ssl.CERT_REQUIRED)

    async def test_empty_provider_output_cannot_claim_a_real_model_result(self):
        base = {'run_id': None}
        with patch.object(gateway, '_run_llm', AsyncMock(return_value='')):
            result = await gateway._dispatch('s', '{}', self.cfg['capability_profiles']['maker'], 't', base, None, 'fallback')
        self.assertEqual(result['mode'], 'zero-llm-error-fallback')
        self.assertIn('Provider request failed', result['reason'])

    async def test_repository_completion_never_replaces_concurrent_web_plan(self):
        stale = {'id': 'run', 'source': {'github_url': 'https://github.com/owner/repo'},
                 'plan': [{'id': 'SEC-01', 'state': 'planned'}, {'id': 'WEB-01', 'state': 'planned'}]}
        fresh = {**stale, 'web_security_scan': {'status': 'completed'}}
        runs = SimpleNamespace(find_one=AsyncMock(side_effect=[stale, fresh]), update_one=AsyncMock())
        db = SimpleNamespace(studio_runs=runs)
        result = {'project': {'id': 'p1', 'name': 'Pilot'}, 'finding_summary': {'total': 1}}
        with patch.object(studio, 'db', db), \
             patch.object(studio.auth, 'require_any_global_role', AsyncMock()), \
             patch.object(studio.auth, 'ensure_project_assignments', AsyncMock()), \
             patch.object(studio.repo_ingest, 'ingest_repo', AsyncMock(return_value=result)), \
             patch.object(studio.ledger_mod, 'append_to_ledger', AsyncMock(return_value={'seq': 1, 'hash': 'h', 'id': 'l'})):
            response = await studio.run_studio_repository_audit('run', {'id': 'u'})
        update = runs.update_one.await_args.args[1]['$set']
        self.assertNotIn('plan', update)
        self.assertEqual(update['plan.$[step].state'], 'completed_source_scan')
        self.assertEqual(response['web_security_scan']['status'], 'completed')

    def test_deterministic_summary_uses_real_counts(self):
        summary = deterministic_report_summary([{'verdict': 'FAIL', 'severity': 'high'},
                                                {'verdict': 'NOT ASSESSED', 'severity': 'info'}])
        self.assertIn('2 findings', summary)
        self.assertIn('1 FAIL', summary)
        self.assertNotIn('would assess', summary)

    def test_historical_placeholder_render_does_not_mutate_original(self):
        original = {'narrative': 'Zero-LLM mode: agent would assess evidence.', 'finding_count': 8, 'ledger_hash': 'original'}
        before = dict(original)
        self.assertIn('8 findings', report_narrative(original))
        self.assertNotIn('would assess', report_narrative(original))
        self.assertEqual(original, before)


if __name__ == '__main__':
    unittest.main()
