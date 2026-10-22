import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock

import pytest
from playwright.async_api import BrowserContext

from config import EdgeSettings, RuntimeSettings
from runtime import supervisor
from runtime.state import RuntimeIdentity


def test_worker_restarts_after_failure_and_normal_exit(
    monkeypatch: pytest.MonkeyPatch, runtime_settings: RuntimeSettings
) -> None:
    processes = [Mock(returncode=code, wait=AsyncMock(return_value=code)) for code in (1, 0)]
    launch = AsyncMock(side_effect=processes)
    sleep = AsyncMock(side_effect=[None, InterruptedError("test completed")])
    monkeypatch.setattr(supervisor.asyncio, "create_subprocess_exec", launch)
    monkeypatch.setattr(supervisor.asyncio, "sleep", sleep)
    with pytest.raises(InterruptedError):
        asyncio.run(
            supervisor.maintain_worker(
                runtime_settings.worker, RuntimeIdentity(project="project", service="worker"), {}
            )
        )
    assert launch.await_count == 2
    assert launch.await_args_list[0] == launch.await_args_list[1]


def test_worker_is_terminated_on_supervisor_cancellation(
    monkeypatch: pytest.MonkeyPatch, runtime_settings: RuntimeSettings
) -> None:
    child = Mock(returncode=None)
    child.wait = AsyncMock(side_effect=[asyncio.CancelledError(), -15])
    monkeypatch.setattr(supervisor.asyncio, "create_subprocess_exec", AsyncMock(return_value=child))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            supervisor.maintain_worker(
                runtime_settings.worker, RuntimeIdentity(project="project", service="worker"), {}
            )
        )
    child.terminate.assert_called_once()
    assert child.wait.await_count == 2


def test_idle_edge_reopens_same_profile(
    monkeypatch: pytest.MonkeyPatch, runtime_settings: RuntimeSettings
) -> None:
    profiles = []

    @asynccontextmanager
    async def launch(settings: EdgeSettings) -> AsyncGenerator[BrowserContext]:
        profiles.append(settings.browser_profile_directory)
        context = Mock(spec=BrowserContext)
        context.on.side_effect = lambda event, callback: callback(context)
        yield context

    monkeypatch.setattr(supervisor, "launch_edge", launch)
    monkeypatch.setattr(
        supervisor.asyncio,
        "sleep",
        AsyncMock(side_effect=[None, InterruptedError("test completed")]),
    )
    with pytest.raises(InterruptedError):
        asyncio.run(supervisor.maintain_edge(runtime_settings.edge))
    assert profiles == [runtime_settings.edge.browser_profile_directory] * 2
