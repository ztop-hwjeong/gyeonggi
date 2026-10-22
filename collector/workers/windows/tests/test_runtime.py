import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from playwright.async_api import BrowserContext

from config import RuntimeSettings
from flows import runtime


def test_windows_flow_rejects_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime.platform, "system", lambda: "Linux")
    with pytest.raises(RuntimeError, match="Windows 실행 환경 필요"):
        asyncio.run(runtime.windows_browser_check.fn())


def test_windows_flow_reuses_browser_page(
    monkeypatch: pytest.MonkeyPatch, runtime_settings: RuntimeSettings
) -> None:
    context = AsyncMock(spec=BrowserContext)
    page = AsyncMock()
    context.pages = [page]

    monkeypatch.setattr(runtime.platform, "system", lambda: "Windows")
    monkeypatch.setattr(runtime, "get_run_logger", Mock())
    settings_factory = Mock()
    settings_factory.model_validate.return_value = runtime_settings.browser
    monkeypatch.setattr(runtime, "BrowserSettings", settings_factory)
    recovery_factory = Mock()
    recovery_factory.model_validate.return_value = runtime_settings.recovery
    monkeypatch.setattr(runtime, "RecoverySettings", recovery_factory)

    async def run_operation(settings, recovery, operation):
        assert settings is runtime_settings.browser
        assert recovery is runtime_settings.recovery
        return await operation(context)

    operation_runner = AsyncMock(side_effect=run_operation)
    monkeypatch.setattr(runtime, "run_edge_operation", operation_runner)
    result = asyncio.run(runtime.windows_browser_check.fn())
    context.new_page.assert_not_awaited()
    context.close.assert_not_awaited()
    assert result["browser"] == "msedge"
    page.goto.assert_awaited_once_with("about:blank", wait_until="domcontentloaded", timeout=30_000)
