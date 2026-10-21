"""Offline orchestration tests: no real target, provider call or MongoDB required."""
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault('MONGO_URL', 'mongodb://127.0.0.1:27017')
os.environ.setdefault('DB_NAME', 'workspace_test')
from routers import testing_workspace as ws


def finish(coroutine):
    try:
        coroutine.send(None)
    except StopIteration as result:
        return result.value
    raise AssertionError('Unexpected real asynchronous I/O')


class WorkspaceRouteTests(unittest.TestCase):
    def setUp(self):
        self.case = {'id': 'TC-1', 'title': 'Dashboard visible', 'source_ids': ['R1'], 'steps': ['Open dashboard'],
                     'expected': 'Dashboard heading is shown', 'category': 'functional', 'oracle': {'op': 'assert_text', 'value': 'Dashboard'}}
        self.record = {'id': 'session1', 'owner_id': 'user1', 'browser_id': 'browser1', 'status': 'running',
                       'expires_at': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                       'plan': {'cases': [self.case]}, 'approved_plan_hash': 'hash', 'origins': ['https://example.test:443'],
                       'sources': [{'id': 'R1', 'text': 'Dashboard shall be visible'}], 'results': [], 'action_history': []}
        self.collection = SimpleNamespace(find_one=AsyncMock(side_effect=lambda *args, **kw: dict(self.record)),
            update_one=AsyncMock(return_value=SimpleNamespace(modified_count=1)))
        self.fake_db = SimpleNamespace(testing_sessions=self.collection)
        self.view = {'url': 'https://example.test/', 'text': 'Dashboard', 'controls': [{'node': 'n1', 'label': 'Create', 'type': 'button'}],
                     'observation_id': 'obs1', 'pending_requests': [], 'busy': False, 'last_action': {'ok': True, 'assertion': True, 'op': 'assert_text'}}
        self.worker = AsyncMock(return_value=self.view)
        self.event = AsyncMock()
        self.save = AsyncMock()
        self.stack = []
        for target, value in [('db', self.fake_db), ('worker', self.worker), ('event', self.event), ('save_result', self.save)]:
            patcher = patch.object(ws, target, value); patcher.start(); self.addCleanup(patcher.stop)

    def run_agent(self, action):
        with patch.object(ws, 'model', AsyncMock(return_value={'mode': 'llm', 'text': json.dumps(action)})), \
             patch.object(ws.asyncio, 'get_running_loop', return_value=SimpleNamespace(time=lambda: 0)):
            finish(ws.run_cases(dict(self.record)))

    def test_pass_requires_the_approved_oracle_and_browser_success(self):
        self.run_agent({'op': 'assert_text', 'value': 'Dashboard'})
        self.assertEqual(self.save.await_args.args[2], 'PASS')
        self.worker.assert_any_await('POST', '/sessions/browser1/action', ws.BrowserAction(op='assert_text', value='Dashboard').model_dump())

    def test_browser_assertion_failure_is_fail(self):
        self.view['last_action']['ok'] = False
        self.run_agent({'op': 'assert_text', 'value': 'Dashboard'})
        self.assertEqual(self.save.await_args.args[2], 'FAIL')

    def test_model_cannot_substitute_a_weaker_assertion(self):
        self.run_agent({'op': 'assert_text', 'value': 'anything'})
        self.save.assert_not_awaited()
        self.assertFalse(any(call.args[0] == 'POST' for call in self.worker.await_args_list))

    def test_model_click_is_a_proposal_until_human_approves(self):
        self.run_agent({'op': 'click', 'node': 'n1', 'observation_id': 'obs1', 'reason': 'Open create form'})
        self.assertFalse(any(call.args[0] == 'POST' for call in self.worker.await_args_list))
        updates = [call.args[1] for call in self.collection.update_one.await_args_list]
        self.assertTrue(any(item.get('$set', {}).get('status') == 'awaiting_action' for item in updates))

    def test_password_control_requires_human_handoff(self):
        self.view['controls'][0]['type'] = 'password'
        self.run_agent({'op': 'fill', 'node': 'n1', 'value': 'never-type-this'})
        self.assertFalse(any(call.args[0] == 'POST' for call in self.worker.await_args_list))
        self.assertTrue(any(call.args[1].get('$set', {}).get('status') == 'handoff' for call in self.collection.update_one.await_args_list))

    def test_no_assertion_or_nonfunctional_case_is_blocked(self):
        self.case['oracle'] = None
        self.run_agent({'op': 'blocked'})
        self.assertEqual(self.save.await_args.args[2], 'BLOCKED')
        self.worker.assert_not_awaited()

    def test_secure_input_never_enters_transcript_or_persistence(self):
        self.record['status'] = 'paused'
        self.worker.return_value = {'accepted': True}
        canary = 'synthetic-password-that-must-not-be-saved'
        request = ws.ManualInput(op='fill', node='focused', value=canary, secret=True)
        with patch.object(ws, 'owned', AsyncMock(return_value=self.record)):
            finish(ws.manual_input('session1', request, {'id': 'user1'}))
        self.assertNotIn(canary, str(self.collection.update_one.await_args_list))
        self.assertNotIn(canary, str(self.event.await_args_list))
        self.assertIn(canary, str(self.worker.await_args_list))  # only intended destination: live browser field

    def test_missing_model_stops_without_an_invented_result(self):
        with patch.object(ws, 'model', AsyncMock(return_value={'mode': 'budget-exhausted', 'text': ''})), \
             patch.object(ws.asyncio, 'get_running_loop', return_value=SimpleNamespace(time=lambda: 0)):
            finish(ws.run_cases(dict(self.record)))
        self.save.assert_not_awaited()
        self.assertFalse(any(call.args[0] == 'POST' for call in self.worker.await_args_list))

    def test_approved_direct_page_check_runs_without_any_model_call(self):
        self.case.update({'execution': 'page_assertion', 'navigation_url': 'https://example.test/'})
        def update(query, change):
            history = change.get('$push', {}).get('action_history')
            if history:
                self.record['action_history'].extend(history['$each'])
            return SimpleNamespace(modified_count=1, matched_count=1)
        self.collection.update_one.side_effect = update
        def browser(method, path, body=None):
            if method == 'POST':
                self.view['last_action'] = {'op': body['op'], 'ok': True, 'assertion': body['op'].startswith('assert_')}
            return self.view
        self.worker.side_effect = browser
        provider = AsyncMock(side_effect=AssertionError('No model should be called'))
        with patch.object(ws, 'model', provider), patch.object(ws.asyncio, 'get_running_loop', return_value=SimpleNamespace(time=lambda: 0)):
            finish(ws.run_cases(dict(self.record)))
        provider.assert_not_awaited()
        self.assertEqual(self.save.await_args.args[2], 'PASS')

    def test_workspace_model_requires_cloud_consent_and_uses_studio_budget(self):
        cfg = {'zero_llm_mode': False, 'max_llm_calls_per_run': 12, 'sovereignty': {},
               'capability_profiles': {'maker': {'provider': 'openai', 'model': 'configured-model'}}}
        dispatch = AsyncMock(return_value={'mode': 'llm', 'text': '{}'})
        with patch.object(ws.gateway, 'get_config', AsyncMock(return_value=cfg)), patch.object(ws.gateway, '_dispatch', dispatch):
            result = finish(ws.gateway.complete_workspace('system', '{}', db=self.fake_db, run_id='workspace-session1'))
            self.assertEqual(result['mode'], 'sovereignty-blocked')
            dispatch.assert_not_awaited()
            finish(ws.gateway.complete_workspace('system', '{}', db=self.fake_db, run_id='workspace-session1', allow_cloud=True, project_id='project-fixture'))
            self.assertEqual(ws.gateway.get_config.await_args.args, (self.fake_db, 'project-fixture'))
        self.assertEqual(dispatch.await_args.args[-1], 12)
        self.assertEqual(dispatch.await_args.args[4]['run_id'], 'workspace-session1')

    def test_ownership_is_enforced_in_database_query(self):
        self.collection.find_one.return_value = None
        self.collection.find_one.side_effect = None
        with patch.object(ws.auth, 'require_any_global_role', AsyncMock()):
            with self.assertRaises(ws.HTTPException) as raised:
                finish(ws.owned('session1', {'id': 'someone-else'}))
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(self.collection.find_one.await_args.args[0]['owner_id'], 'someone-else')

    def test_project_role_revocation_blocks_an_existing_session_owner(self):
        self.record['project_id'] = 'project1'
        with patch.object(ws.auth, 'require_any_global_role', AsyncMock()), patch.object(ws.auth, 'roles_for', AsyncMock(return_value=[])):
            with self.assertRaises(ws.HTTPException) as raised:
                finish(ws.owned('session1', {'id': 'user1'}))
        self.assertEqual(raised.exception.status_code, 403)


class WorkspaceHttpTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        self.app = FastAPI()
        self.app.include_router(ws.router, prefix='/api')
        self.app.dependency_overrides[ws.auth.get_current_user] = lambda: {'id': 'owner1'}
        self.client = TestClient(self.app)
        self.collection = SimpleNamespace(insert_one=AsyncMock())
        self.worker = AsyncMock(return_value={'id': 'browser1', 'scopes': ['https://example.test:443']})
        for target, value in [('db', SimpleNamespace(testing_sessions=self.collection)),
                              ('worker', self.worker), ('audit', AsyncMock()), ('event', AsyncMock()), ('spawn', lambda *args: None)]:
            patcher = patch.object(ws, target, value); patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch.object(ws.auth, 'require_any_global_role', AsyncMock()); patcher.start(); self.addCleanup(patcher.stop)

    def test_form_intake_opens_worker_only_after_authorization(self):
        payload = {'url': 'https://example.test/', 'name': 'Fixture', 'authorization_owner': 'Fixture owner',
                   'authorization_reference': 'TEST-001', 'requirements': 'REQ-1 The home page shall show Welcome.'}
        response = self.client.post('/api/testing-workspace/sessions', data=payload)
        self.assertEqual(response.status_code, 400)
        self.worker.assert_not_awaited()
        payload['authorized'] = 'true'
        response = self.client.post('/api/testing-workspace/sessions', data=payload)
        self.assertEqual(response.status_code, 201, response.text)
        record = self.collection.insert_one.await_args.args[0]
        self.assertEqual(record['owner_id'], 'owner1')
        self.assertEqual(record['status'], 'planning')
        self.assertFalse(record['allow_cloud'])
        self.assertTrue(record['sources'])

    def test_invalid_secure_input_does_not_echo_request_value(self):
        response = self.client.post('/api/testing-workspace/sessions/fixture/input',
            json={'op': 'fill', 'node': 'focused', 'secret': True, 'value': 'private-canary-' * 200})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn('private-canary', response.text)


if __name__ == '__main__': unittest.main()
