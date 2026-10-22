import asyncio
import logging
from collections.abc import Awaitable, Callable

from playwright.async_api import BrowserContext, Error

from browser.connection import BrowserUnavailableError, open_edge
from config import BrowserSettings, RecoverySettings


class BrowserClosedError(RuntimeError):
    pass


async def run_in_context[T](
    context: BrowserContext, operation: Callable[[BrowserContext], Awaitable[T]]
) -> T:
    closed = asyncio.Event()

    def on_close(_: BrowserContext) -> None:
        closed.set()

    context.on("close", on_close)
    work = asyncio.ensure_future(operation(context))
    closure = asyncio.create_task(closed.wait())
    try:
        await asyncio.wait({work, closure}, return_when=asyncio.FIRST_COMPLETED)
        if closed.is_set():
            raise BrowserClosedError("작업 도중 Edge 창 종료")
        try:
            return await work
        except Error as error:
            if closed.is_set():
                raise BrowserClosedError("작업 도중 Edge 창 종료") from error
            raise
    finally:
        context.remove_listener("close", on_close)
        work.cancel()
        closure.cancel()
        await asyncio.gather(work, closure, return_exceptions=True)


async def run_edge_operation[T](
    browser: BrowserSettings,
    recovery: RecoverySettings,
    operation: Callable[[BrowserContext], Awaitable[T]],
) -> T:
    remaining = recovery.browser_operation_attempts
    while True:
        try:
            async with open_edge(browser) as context:
                return await run_in_context(context, operation)
        except (BrowserClosedError, BrowserUnavailableError):
            remaining -= 1
            if remaining == 0:
                raise
            logging.getLogger(__name__).warning("Edge 연결 종료 감지: 작업 재시도")
            await asyncio.sleep(recovery.browser_operation_retry_delay)
