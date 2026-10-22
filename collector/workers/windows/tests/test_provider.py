import json
from unittest.mock import Mock

import pytest

from compose import provider
from config import RuntimeSettings


def test_metadata_does_not_require_runtime_configuration(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert provider.main(["compose", "metadata"]) == 0
    assert "up" in json.loads(capsys.readouterr().out)


def test_up_delegates_to_process_management(
    monkeypatch: pytest.MonkeyPatch,
    runtime_settings: RuntimeSettings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings_factory = Mock()
    settings_factory.load.return_value = runtime_settings
    monkeypatch.setattr(provider, "RuntimeSettings", settings_factory)
    launch = Mock()
    monkeypatch.setattr(provider, "start_supervisor", launch)
    assert provider.main(["compose", "--project-name", "project", "up", "worker"]) == 0
    launch.assert_called_once()
    assert launch.call_args.args[1].name == "project-worker"
    assert json.loads(capsys.readouterr().out)["type"] == "info"


def test_bad_identity_fails_without_starting_process(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    launch = Mock()
    monkeypatch.setattr(provider, "start_supervisor", launch)
    assert provider.main(["compose", "--project-name", "../other", "up", "worker"]) == 1
    launch.assert_not_called()
    assert json.loads(capsys.readouterr().out)["type"] == "error"


def test_down_does_not_load_browser_settings(
    monkeypatch: pytest.MonkeyPatch,
    runtime_settings: RuntimeSettings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime_factory = Mock()
    runtime_factory.load.side_effect = AssertionError("Browser settings must not be loaded")
    worker_factory = Mock()
    worker_factory.model_validate.return_value = runtime_settings.worker
    stop = Mock()
    monkeypatch.setattr(provider, "RuntimeSettings", runtime_factory)
    monkeypatch.setattr(provider, "WorkerSettings", worker_factory)
    monkeypatch.setattr(provider, "stop_supervisor", stop)

    assert provider.main(["compose", "--project-name", "project", "down", "worker"]) == 0
    stop.assert_called_once()
    assert json.loads(capsys.readouterr().out)["type"] == "info"
