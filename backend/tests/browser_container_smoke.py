"""Run inside the built non-root worker image, with no external target traffic."""
import asyncio
import os
from playwright.async_api import async_playwright
from browser_worker import BrowserSession, InputAction


async def main():
    if hasattr(os, 'geteuid'):
        assert os.geteuid() != 0, 'The browser smoke must run as a non-root container user'
    async with async_playwright() as playwright:
        session = BrowserSession(playwright, set())
        try:
            await session.start('about:blank')
            await session.page.set_content('<h1>Browser container ready</h1><input type="password" value="container-canary">')
            await session.execute(InputAction(op='assert_text', value='Browser container ready'))
            assert session.last_action['ok'], 'Container browser assertion failed'
            view = await session.observe()
            assert view['frame'] and 'container-canary' not in str(view), 'Container frame/privacy check failed'
            print('Browser worker smoke passed')
        finally:
            await session.close()


asyncio.run(main())
