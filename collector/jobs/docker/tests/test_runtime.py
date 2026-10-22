from unittest.mock import Mock

import pytest

from flows import runtime


def test_docker_flow_runs_on_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime.platform, "system", lambda: "Linux")
    monkeypatch.setattr(runtime, "get_run_logger", Mock())
    assert runtime.docker_runtime_check.fn()["platform"] == "Linux"


def test_docker_flow_rejects_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime.platform, "system", lambda: "Windows")
    with pytest.raises(RuntimeError, match="실행 환경 불일치"):
        runtime.docker_runtime_check.fn()
