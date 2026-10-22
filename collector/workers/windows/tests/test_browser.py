import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock

import pytest
from playwright.async_api import BrowserContext

from browser import connection, recovery
from config import BrowserSettings, RuntimeSettings


@pytest.mark.parametrize("fail", [False, True])
def test_browser_context_is_closed_on_success_and_failure(
    monkeypatch: pytest.MonkeyPatch, runtime_settings: RuntimeSettings, fail: bool
) -> None:
    context = AsyncMock(spec=BrowserContext)
    driver = Mock()
    driver.chromium.launch_persistent_context = AsyncMock(return_value=context)
    manager = AsyncMock()
    manager.__aenter__.return_value = driver
    monkeypatch.setattr(connection, "async_playwright", lambda: manager)

    async def run() -> None:
        async with connection.launch_edge(runtime_settings.edge) as opened:
            assert opened is context
            if fail:
                raise RuntimeError("수집 실패")

    if fail:
        with pytest.raises(RuntimeError, match="수집 실패"):
            asyncio.run(run())
    else:
        asyncio.run(run())

    driver.chromium.launch_persistent_context.assert_awaited_once_with(
        user_data_dir=runtime_settings.edge.browser_profile_directory,
        channel="msedge",
        headless=False,
        chromium_sandbox=True,
        timeout=30_000,
        args=["--remote-debugging-port=9222", "--remote-debugging-address=127.0.0.1"],
    )
    context.close.assert_awaited_once()


@pytest.mark.parametrize("closures", [0, 1, 3])
def test_window_close_reconnects_without_waiting_for_operation(
    monkeypatch: pytest.MonkeyPatch, runtime_settings: RuntimeSettings, closures: int
) -> None:
    contexts = []

    @asynccontextmanager
    async def open_context(settings: BrowserSettings) -> AsyncGenerator[BrowserContext]:
        context = Mock(spec=BrowserContext)
        contexts.append(context)
        yield context

    async def operation(context: BrowserContext) -> str:
        if len(contexts) <= closures:
            contexts[-1].on.call_args.args[1](context)
            await asyncio.Event().wait()
        return "completed"

    monkeypatch.setattr(recovery, "open_edge", open_context)
    if closures == 3:
        with pytest.raises(recovery.BrowserClosedError, match="Edge 창 종료"):
            asyncio.run(
                recovery.run_edge_operation(
                    runtime_settings.browser, runtime_settings.recovery, operation
                )
            )
    else:
        assert (
            asyncio.run(
                recovery.run_edge_operation(
                    runtime_settings.browser, runtime_settings.recovery, operation
                )
            )
            == "completed"
        )
    assert len(contexts) == min(closures + 1, 3)


def test_operation_error_is_not_treated_as_window_close(
    monkeypatch: pytest.MonkeyPatch, runtime_settings: RuntimeSettings
) -> None:
    opens = []

    @asynccontextmanager
    async def open_context(settings: BrowserSettings) -> AsyncGenerator[BrowserContext]:
        opens.append(True)
        yield Mock(spec=BrowserContext)

    async def operation(context: BrowserContext) -> None:
        raise RuntimeError("수집 데이터 오류")

    monkeypatch.setattr(recovery, "open_edge", open_context)
    with pytest.raises(RuntimeError, match="수집 데이터 오류"):
        asyncio.run(
            recovery.run_edge_operation(
                runtime_settings.browser, runtime_settings.recovery, operation
            )
        )
    assert opens == [True]


@pytest.mark.parametrize("fail", [False, True])
def test_job_disconnects_without_closing_shared_browser(
    monkeypatch: pytest.MonkeyPatch, runtime_settings: RuntimeSettings, fail: bool
) -> None:
    context = AsyncMock(spec=BrowserContext)
    cdp_connection = AsyncMock()
    cdp_connection.contexts = [context]
    driver = Mock()
    driver.chromium.connect_over_cdp = AsyncMock(return_value=cdp_connection)
    manager = AsyncMock()
    manager.__aenter__.return_value = driver
    monkeypatch.setattr(connection, "async_playwright", lambda: manager)

    async def run() -> None:
        async with connection.open_edge(runtime_settings.browser) as opened:
            assert opened is context
            if fail:
                raise RuntimeError("수집 실패")

    if fail:
        with pytest.raises(RuntimeError, match="수집 실패"):
            asyncio.run(run())
    else:
        asyncio.run(run())
    context.close.assert_not_awaited()
    cdp_connection.close.assert_awaited_once()
