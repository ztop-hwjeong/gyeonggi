import asyncio
import platform

from playwright.async_api import BrowserContext
from prefect import flow, get_run_logger

from browser.recovery import run_edge_operation
from config import BrowserSettings, RecoverySettings


@flow(name="windows-browser-check", timeout_seconds=120)
async def windows_browser_check(
    url: str = "about:blank", screenshot_path: str | None = None, hold_seconds: int = 0
) -> dict[str, str]:
    if platform.system() != "Windows":
        raise RuntimeError("Windows 실행 환경 필요")
    if not 0 <= hold_seconds <= 60:
        raise ValueError("화면 유지 시간은 0~60초 범위")
    logger = get_run_logger()
    browser_settings = BrowserSettings.model_validate({})
    recovery_settings = RecoverySettings.model_validate({})

    async def check_browser(context: BrowserContext) -> dict[str, str]:
        logger.info("Edge 프로필 연결 완료")
        page = context.pages[0] if context.pages else await context.new_page()
        logger.info("페이지 이동 시작: %s", url)
        await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=browser_settings.browser_navigation_timeout_ms,
        )
        logger.info("페이지 이동 완료: %s", page.url)
        if hold_seconds:
            logger.info("화면 확인 대기: %s초", hold_seconds)
            await asyncio.sleep(hold_seconds)
        if screenshot_path is not None:
            await page.screenshot(path=screenshot_path)
            logger.info("화면 캡처 완료")
        result = {
            "hostname": platform.node(),
            "platform": platform.system(),
            "python": platform.python_version(),
            "browser": "msedge",
            "url": page.url,
            "title": await page.title(),
        }
        logger.info("Windows 브라우저 실행 환경 확인: %s", result)
        return result

    return await run_edge_operation(browser_settings, recovery_settings, check_browser)
