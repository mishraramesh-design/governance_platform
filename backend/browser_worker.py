"""Private Playwright worker. No database, provider keys or public control port.

The browser stream is a sequence of authenticated JPEG frames with semantic
controls, not an iframe of the target. All cookies and credentials are ephemeral.
"""
import asyncio
import base64
import hashlib
import ipaddress
import json
import os
import secrets
import socket
import time
from contextlib import asynccontextmanager, suppress
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import Field
from workspace_core import Contract, BrowserAction, origin, masked

SESSIONS = {}
MAX_SESSIONS = 1
IDLE_SECONDS = 1800


async def authorize(x_browser_token: str = Header(default='')):
    expected = os.environ.get('BROWSER_WORKER_TOKEN', '')
    if not expected or not secrets.compare_digest(x_browser_token, expected):
        raise HTTPException(401, 'Worker authentication required.')


async def resolve_public(url):
    parsed = urlsplit(url)
    origin(url)
    if parsed.fragment or parsed.username or parsed.password:
        raise ValueError('Credentials and fragments are not allowed in navigation URLs.')
    answers = await asyncio.get_running_loop().getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), type=socket.SOCK_STREAM)
    ips = sorted({item[4][0] for item in answers})
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise ValueError('Only public target addresses are allowed.')
    return ips[0]


class OpenBrowser(Contract):
    url: str = Field(min_length=8, max_length=2048)
    allowed_origins: list[str] = Field(default_factory=list, max_length=8)


class InputAction(BrowserAction):
    secret: bool = False


class Decision(Contract):
    allow: bool


class BrowserSession:
    def __init__(self, playwright, scopes):
        self.playwright = playwright
        self.scopes = scopes
        self.browser = self.context = self.page = None
        self.pending = {}
        self.active_writes = set()
        self.blocked_origins = set()
        self.nodes = {}
        self.observation_id = ''
        self.frame = b''
        self.touched = time.monotonic()
        self.expires_at = time.monotonic() + 7200
        self.lock = asyncio.Lock()
        self.busy = None
        self.last_action = None
        self.last_view = {'url': '', 'text': '', 'controls': [], 'observation_id': '', 'frame': '',
                          'frame_sha256': None, 'viewport': {'width': 1280, 'height': 800}}
        self.closed = False

    async def start(self, url):
        mappings = []
        for scope in self.scopes:
            ip = await resolve_public(scope)
            mappings.append(f'MAP {urlsplit(scope).hostname} {ip}')
        browser_env = {key: value for key, value in os.environ.items() if key.upper() in {
            'PATH', 'HOME', 'LANG', 'TMPDIR', 'TEMP', 'TMP', 'SYSTEMROOT', 'WINDIR', 'USERPROFILE', 'LOCALAPPDATA'}}
        self.browser = await self.playwright.chromium.launch(headless=True, env=browser_env, args=[
            '--disable-dev-shm-usage', '--no-proxy-server',
            '--host-resolver-rules=' + ','.join(mappings),
            '--disable-features=WebRtcHideLocalIpsWithMdns',
            '--force-webrtc-ip-handling-policy=disable_non_proxied_udp',
        ])
        self.context = await self.browser.new_context(viewport={'width': 1280, 'height': 800},
                                                      service_workers='block', accept_downloads=False)
        self.context.set_default_timeout(4000)
        await self.context.route('**/*', self.guard)
        await self.context.route_web_socket('**/*', lambda route: route.close())
        self.context.on('page', self.new_page)
        self.context.on('requestfinished', lambda request: self.active_writes.discard(request))
        self.context.on('requestfailed', lambda request: self.active_writes.discard(request))
        self.page = await self.context.new_page()
        try:
            await self.page.goto(url, wait_until='domcontentloaded', timeout=20000)
            self.last_action = {'op': 'initial_navigation', 'ok': True}
        except Exception as exc:
            self.last_action = {'op': 'initial_navigation', 'ok': False, 'error': type(exc).__name__}

    async def new_page(self, page):
        page.on('dialog', lambda dialog: dialog.dismiss())
        if self.page is not None and page != self.page:
            # Popup authentication needs a separately authorized flow; never hide a second browsing surface.
            await page.close()

    async def guard(self, route):
        request = route.request
        try:
            if self.closed or time.monotonic() >= self.expires_at:
                return await route.abort('blockedbyclient')
            request_origin = origin(request.url)
            if request_origin not in self.scopes:
                self.blocked_origins.add(masked(request_origin, 250))
                return await route.abort('blockedbyclient')
            if request.method not in ('GET', 'HEAD', 'OPTIONS'):
                if len(self.pending) >= 8:
                    return await route.abort('blockedbyclient')
                key = uuid4().hex
                event = asyncio.Event()
                # Only the request's method, origin and path are exposed. Payload stays in Chromium memory.
                parsed = urlsplit(request.url)
                decision = {'id': key, 'method': request.method, 'url': masked(request_origin + parsed.path, 1000),
                            'payload_bytes': len(request.post_data_buffer or b''), 'event': event, 'allow': False}
                self.pending[key] = decision
                try:
                    await asyncio.wait_for(event.wait(), timeout=300)
                    if decision['allow'] and not self.closed and time.monotonic() < self.expires_at:
                        self.active_writes.add(request)
                        return await route.continue_()
                    return await route.abort('blockedbyclient')
                finally:
                    self.pending.pop(key, None)
            return await route.continue_()
        except Exception:
            with suppress(Exception):
                await route.abort('blockedbyclient')

    async def observe(self):
        self.touched = time.monotonic()
        async with self.lock:
            if self.closed:
                raise HTTPException(410, 'Browser session closed.')
            if (self.busy and not self.busy.done()) or self.active_writes:
                return {**self.last_view, 'pending_requests': [{k: v for k, v in item.items() if k not in ('event', 'allow')} for item in self.pending.values()],
                        'blocked_origins': sorted(self.blocked_origins), 'busy': True, 'last_action': self.last_action}
            # Do not remap node IDs in the middle of an action or while an agent consumes an observation.
            nodes = {}
            controls = []
            observation_id = uuid4().hex
            text = ''
            try:
                text = masked(await self.page.locator('body').inner_text(timeout=2500), 12000)
                elements = self.page.locator('a,button,input,textarea,select,[role="button"],[contenteditable="true"]')
                for index in range(min(await elements.count(), 120)):
                    element = elements.nth(index)
                    if not await element.is_visible():
                        continue
                    node = f'n{index}'
                    tag = await element.evaluate('(el) => el.tagName.toLowerCase()')
                    typ = await element.get_attribute('type') or ''
                    label = await element.get_attribute('aria-label') or await element.get_attribute('placeholder') or await element.get_attribute('name') or ''
                    if tag in ('button', 'a'):
                        label = (await element.inner_text())[:180] or label
                    controls.append({'node': node, 'tag': tag, 'type': typ, 'label': masked(label, 200),
                                     'href': masked(await element.get_attribute('href') or '', 300) if tag == 'a' else ''})
                    nodes[node] = await element.element_handle()
                observation_id = hashlib.sha256(json.dumps([self.page.url, controls], sort_keys=True).encode()).hexdigest()
                for handle in self.nodes.values():
                    if hasattr(handle, 'dispose'):
                        with suppress(Exception):
                            await handle.dispose()
                self.nodes = nodes
                self.observation_id = observation_id
                self.frame = await self.page.screenshot(type='jpeg', quality=60, timeout=3000,
                    mask=[self.page.locator('input,textarea,[contenteditable="true"]')])
            except Exception:
                # Navigation awaiting an approved request may temporarily prevent a new frame.
                observation_id = self.observation_id
            result = {'url': masked(self.page.url, 2000), 'text': text, 'controls': controls,
                    'observation_id': observation_id, 'frame': base64.b64encode(self.frame).decode(),
                    'frame_sha256': hashlib.sha256(self.frame).hexdigest() if self.frame else None,
                    'pending_requests': [{k: v for k, v in item.items() if k not in ('event', 'allow')} for item in self.pending.values()],
                    'blocked_origins': sorted(self.blocked_origins), 'busy': bool((self.busy and not self.busy.done()) or self.active_writes),
                    'last_action': self.last_action, 'viewport': {'width': 1280, 'height': 800}}
            self.last_view = dict(result)
            return result

    async def execute(self, action):
        self.touched = time.monotonic()
        op = action.op
        if op in ('click', 'fill', 'select', 'press'):
            if action.node == 'focused' and action.secret and op == 'fill':
                element = self.page.locator('input:focus,textarea:focus,[contenteditable="true"]:focus')
                if await element.count() != 1:
                    raise ValueError('Click an input in the browser before sending secure input.')
            elif action.observation_id != self.observation_id or action.node not in self.nodes:
                raise ValueError('Controls changed. Refresh the browser view and choose the control again.')
            else:
                element = self.nodes[action.node]
        try:
            if op == 'navigate':
                if origin(action.value) not in self.scopes:
                    raise ValueError('Navigation is outside the approved origins.')
                await self.page.goto(action.value, wait_until='domcontentloaded', timeout=15000)
            elif op == 'click':
                await element.click(timeout=5000, no_wait_after=True)
            elif op == 'fill':
                await element.fill(action.value, timeout=5000)
            elif op == 'select':
                await element.select_option(action.value, timeout=5000)
            elif op == 'press':
                if action.value not in ('Enter', 'Tab', 'Escape', 'ArrowDown', 'ArrowUp', 'Space'):
                    raise ValueError('Unsupported browser key.')
                await element.press(action.value, timeout=5000)
            elif op == 'scroll':
                await self.page.mouse.wheel(0, -600 if action.value == 'up' else 600)
            elif op == 'assert_text':
                if not action.value:
                    raise ValueError('An empty assertion is not evidence.')
                from playwright.async_api import expect
                await expect(self.page.locator('body')).to_contain_text(action.value, timeout=5000, use_inner_text=True)
            elif op == 'assert_url':
                if origin(action.value) not in self.scopes or self.page.url != action.value:
                    raise AssertionError('Current URL does not match the approved expected URL.')
            else:
                raise ValueError('This action requires human handoff, not browser execution.')
            self.last_action = {'op': op, 'ok': True, 'assertion': op.startswith('assert_'), 'at': time.time()}
        except Exception as exc:
            # Never log exception messages: Playwright exceptions can contain filled values.
            self.last_action = {'op': op, 'ok': False, 'assertion': op.startswith('assert_'), 'error': type(exc).__name__, 'at': time.time()}

    async def close(self):
        self.closed = True
        for item in list(self.pending.values()):
            item['event'].set()
        if self.busy and not self.busy.done():
            self.busy.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self.busy
        if self.browser:
            await self.browser.close()
        self.nodes.clear()
        self.frame = b''


async def reap():
    while True:
        await asyncio.sleep(30)
        for sid, session in list(SESSIONS.items()):
            if time.monotonic() - session.touched > IDLE_SECONDS or time.monotonic() >= session.expires_at:
                SESSIONS.pop(sid, None)
                with suppress(Exception):
                    await session.close()


@asynccontextmanager
async def lifespan(app):
    from playwright.async_api import async_playwright
    async with async_playwright() as playwright:
        app.state.playwright = playwright
        task = asyncio.create_task(reap())
        yield
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        for session in list(SESSIONS.values()):
            await session.close()
        SESSIONS.clear()


app = FastAPI(title='Private Studio Browser Worker', lifespan=lifespan,
              dependencies=[Depends(authorize)], docs_url=None, redoc_url=None, openapi_url=None)


@app.exception_handler(RequestValidationError)
async def invalid_input(request, exc):
    return JSONResponse(status_code=422, content={'detail': 'Invalid browser input; submitted values are not echoed.'})


admission_lock = asyncio.Lock()


def session_for(sid):
    session = SESSIONS.get(sid)
    if not session:
        raise HTTPException(410, 'Browser expired or worker restarted. Create a new workspace session.')
    if time.monotonic() >= session.expires_at:
        raise HTTPException(410, 'Browser authorization window expired. Create a new session.')
    return session


@app.get('/health')
async def health():
    return {'status': 'ready', 'active_sessions': len(SESSIONS)}


@app.post('/sessions')
async def open_browser(request: OpenBrowser):
    async with admission_lock:
        if len(SESSIONS) >= MAX_SESSIONS:
            raise HTTPException(429, 'Browser capacity reached. Close an existing session.')
        scopes = {origin(request.url), *(origin(url) for url in request.allowed_origins)}
        session = BrowserSession(app.state.playwright, scopes)
        try:
            await session.start(request.url)
        except Exception as exc:
            await session.close()
            raise HTTPException(400, f'Browser could not open the target ({type(exc).__name__}).') from None
        sid = uuid4().hex
        SESSIONS[sid] = session
        return {'id': sid, 'scopes': sorted(scopes)}


@app.get('/sessions/{sid}')
async def observe_browser(sid: str):
    return await session_for(sid).observe()


@app.post('/sessions/{sid}/action')
async def browser_action(sid: str, action: InputAction):
    session = session_for(sid)
    if session.busy and not session.busy.done():
        raise HTTPException(409, 'A browser action is awaiting completion or request approval.')
    if action.secret and action.observation_id != session.observation_id:
        raise HTTPException(409, 'Browser controls changed. Review the focused input before sending secure data.')
    if action.secret and action.node == 'focused' and await session.page.locator('input:focus,textarea:focus,[contenteditable="true"]:focus').count() != 1:
        raise HTTPException(409, 'Click a browser input or select its control before sending secure data.')
    # Stale controls fail synchronously so they cannot be mistaken for completed work.
    if action.op in ('click', 'fill', 'press', 'select') and not (action.secret and action.node == 'focused' and action.op == 'fill') and (action.observation_id != session.observation_id or action.node not in session.nodes):
        raise HTTPException(409, 'Refresh the browser view; the control observation changed.')
    session.last_action = None
    session.busy = asyncio.create_task(session.execute(action))
    try:
        await asyncio.wait_for(asyncio.shield(session.busy), timeout=1)
    except asyncio.TimeoutError:
        pass
    return {'accepted': True}


class Point(Contract):
    x: int = Field(ge=0, le=1279)
    y: int = Field(ge=0, le=799)


@app.post('/sessions/{sid}/point')
async def click_point(sid: str, point: Point):
    session = session_for(sid)
    if session.busy and not session.busy.done():
        raise HTTPException(409, 'Wait for the current browser action or request approval.')
    session.touched = time.monotonic()
    await session.page.mouse.click(point.x, point.y)
    return {'clicked': True}


@app.post('/sessions/{sid}/requests/{request_id}')
async def decide_request(sid: str, request_id: str, decision: Decision):
    session = session_for(sid)
    item = session.pending.get(request_id)
    if not item:
        raise HTTPException(409, 'Request already resolved or expired.')
    item['allow'] = decision.allow
    session.pending.pop(request_id, None)
    item['event'].set()
    return {'resolved': True}


@app.delete('/sessions/{sid}')
async def close_browser(sid: str):
    session = SESSIONS.pop(sid, None)
    if session:
        await session.close()
    return Response(status_code=204)
