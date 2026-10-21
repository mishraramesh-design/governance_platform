"""Real Chromium tests against a disposable local fixture, never a public target."""
import asyncio
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import AsyncMock, patch

from playwright.async_api import async_playwright
import browser_worker as worker
from workspace_core import origin


class Fixture(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def do_GET(self):
        body = b'''<!doctype html><html><head><title>Workspace fixture</title></head><body>
        <h1>Welcome fixture</h1><label>User <input aria-label="Username" value="fixture-user"></label>
        <input aria-label="Password" type="password" value="private-fixture-canary">
        <button id="save" onclick="fetch('/submit',{method:'POST',body:'test-data'}).then(()=>document.querySelector('h1').textContent='Saved')">Save test record</button>
        <a href="/other">Read another page</a></body></html>'''
        self.send_response(200); self.send_header('Content-Type', 'text/html'); self.end_headers(); self.wfile.write(body)

    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length', 0)))
        self.server.received += 1
        self.send_response(200); self.end_headers(); self.wfile.write(b'ok')


class BrowserWorkerTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
        cls.server.received = 0
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}/'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=5)

    async def asyncSetUp(self):
        self.pw = await async_playwright().start()
        self.session = worker.BrowserSession(self.pw, {origin(self.url)})
        # Test-only DNS override scoped to this disposable local fixture. Production rejects it.
        with patch.object(worker, 'resolve_public', AsyncMock(return_value='127.0.0.1')):
            await self.session.start(self.url)

    async def asyncTearDown(self):
        await self.session.close()
        await self.pw.stop()

    async def test_stream_and_controls_exclude_input_values(self):
        view = await self.session.observe()
        self.assertTrue(view['frame'])
        self.assertEqual(len(view['frame_sha256']), 64)
        self.assertIn('Welcome fixture', view['text'])
        self.assertNotIn('private-fixture-canary', str(view))
        self.assertNotIn('fixture-user', str(view))
        self.assertTrue(any(item['type'] == 'password' for item in view['controls']))

    async def test_real_assertion_drives_verdict(self):
        await self.session.execute(worker.InputAction(op='assert_text', value='Welcome fixture'))
        self.assertTrue(self.session.last_action['ok'])
        await self.session.execute(worker.InputAction(op='assert_url', value=self.url + 'missing'))
        self.assertFalse(self.session.last_action['ok'])

    async def test_secure_input_uses_current_control_and_stays_out_of_observations(self):
        view = await self.session.observe()
        node = next(item['node'] for item in view['controls'] if item['type'] == 'password')
        worker.SESSIONS['secure-fixture'] = self.session
        try:
            with self.assertRaises(worker.HTTPException):
                await worker.browser_action('secure-fixture', worker.InputAction(op='fill', node=node,
                    secret=True, value='do-not-send-to-stale-control', observation_id='stale'))
            await worker.browser_action('secure-fixture', worker.InputAction(op='fill', node=node,
                secret=True, value='new-private-test-value', observation_id=view['observation_id']))
            await self.session.busy
            self.assertEqual(await self.session.page.locator('input[type=password]').input_value(), 'new-private-test-value')
            refreshed = await self.session.observe()
            self.assertNotIn('new-private-test-value', str(refreshed))
        finally:
            worker.SESSIONS.pop('secure-fixture')

    async def test_mutating_request_is_blocked_until_approved(self):
        self.server.received = 0
        view = await self.session.observe()
        node = next(item['node'] for item in view['controls'] if item['label'] == 'Save test record')
        self.session.busy = asyncio.create_task(self.session.execute(worker.InputAction(
            op='click', node=node, observation_id=view['observation_id'])))
        for _ in range(30):
            if self.session.pending: break
            await asyncio.sleep(.1)
        self.assertTrue(self.session.pending)
        self.assertEqual(self.server.received, 0)
        decision = next(iter(self.session.pending.values()))
        decision['allow'] = True; decision['event'].set()
        for _ in range(30):
            if self.server.received: break
            await asyncio.sleep(.1)
        self.assertEqual(self.server.received, 1)
        await self.session.busy

    async def test_unapproved_origin_and_stale_control_are_rejected(self):
        await self.session.page.evaluate("fetch('http://unapproved.invalid/data').catch(()=>{})")
        self.assertTrue(any('unapproved.invalid' in item for item in self.session.blocked_origins))
        worker.SESSIONS['fixture-session'] = self.session
        try:
            with self.assertRaises(worker.HTTPException) as raised:
                await worker.browser_action('fixture-session', worker.InputAction(op='click', node='n1', observation_id='stale'))
            self.assertEqual(raised.exception.status_code, 409)
        finally:
            worker.SESSIONS.pop('fixture-session')


class WorkerNetworkValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_dns_result_is_rejected(self):
        with self.assertRaises(ValueError):
            await worker.resolve_public('http://127.0.0.1:8000/')


class WorkerApiPrivacyTests(unittest.TestCase):
    def test_worker_requires_token_and_does_not_echo_invalid_secret_input(self):
        from fastapi.testclient import TestClient
        with patch.dict('os.environ', {'BROWSER_WORKER_TOKEN': 'test-worker-token'}):
            client = TestClient(worker.app)
            self.assertEqual(client.get('/health').status_code, 401)
            canary = 'private-fixture-canary-' * 150
            response = client.post('/sessions/fixture/action', headers={'X-Browser-Token': 'test-worker-token'},
                json={'op': 'fill', 'node': 'focused', 'secret': True, 'value': canary})
            self.assertEqual(response.status_code, 422)
            self.assertNotIn('private-fixture-canary', response.text)


if __name__ == '__main__': unittest.main()
