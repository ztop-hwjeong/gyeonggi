from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from playwright.async_api import BrowserContext, Error, async_playwright

from config import BrowserSettings, EdgeSettings


class BrowserUnavailableError(RuntimeError):
    pass


@asynccontextmanager
async def open_edge(settings: BrowserSettings) -> AsyncGenerator[BrowserContext]:
    async with async_playwright() as playwright:
        try:
            connection = await playwright.chromium.connect_over_cdp(
                str(settings.browser_cdp_url), timeout=settings.browser_connect_timeout_ms
            )
        except Error as error:
            raise BrowserUnavailableError("관리 중인 Edge 연결 불가") from error
        try:
            yield connection.contexts[0]
        finally:
            # CDP 연결만 해제하고 관리 중인 Edge 창은 유지
            await connection.close()


@asynccontextmanager
async def launch_edge(settings: EdgeSettings) -> AsyncGenerator[BrowserContext]:
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=settings.browser_profile_directory,
            channel="msedge",
            headless=False,
            chromium_sandbox=True,
            timeout=settings.browser_launch_timeout_ms,
            args=[
                f"--remote-debugging-port={settings.browser_cdp_url.port}",
                f"--remote-debugging-address={settings.browser_cdp_url.host}",
            ],
        )
        try:
            yield context
        finally:
            await context.close()
