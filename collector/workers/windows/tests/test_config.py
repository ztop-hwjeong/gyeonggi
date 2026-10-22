from pathlib import Path

import pytest
from pydantic import ValidationError

from config import BrowserSettings, EdgeSettings, RuntimeSettings, WorkerSettings
from runtime.process import subprocess_environment


@pytest.mark.parametrize("subdirectory", ["", "Default"])
def test_default_edge_profile_is_rejected(
    runtime_settings: RuntimeSettings, subdirectory: str
) -> None:
    values = runtime_settings.edge.model_dump()
    values["browser_profile_directory"] = (
        runtime_settings.edge.edge_default_profile_directory / subdirectory
    )
    with pytest.raises(ValidationError, match="수집 전용 프로필"):
        EdgeSettings.model_validate(values)


def test_missing_required_configuration_fails_before_startup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    for field in WorkerSettings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
    with pytest.raises(ValidationError) as error:
        WorkerSettings.model_validate({})
    missing = {item["loc"][0] for item in error.value.errors()}
    assert {"collector_directory", "runtime_directory", "prefect_api_url"} <= missing


def test_settings_survive_child_process_working_directory_change(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, runtime_settings: RuntimeSettings
) -> None:
    for name, value in subprocess_environment(runtime_settings).items():
        monkeypatch.setenv(name, value)
    child_directory = tmp_path / "child"
    child_directory.mkdir()
    monkeypatch.chdir(child_directory)

    loaded = RuntimeSettings.load({})

    assert loaded == runtime_settings
    assert loaded.worker.runtime_directory.is_absolute()


@pytest.mark.parametrize("endpoint", ["http://example.com:9222", "https://127.0.0.1:9222"])
def test_cdp_endpoint_matches_local_browser_binding(endpoint: str) -> None:
    with pytest.raises(ValidationError, match="로컬 HTTP"):
        BrowserSettings.model_validate({"browser_cdp_url": endpoint})


def test_invalid_worker_limit_is_rejected(runtime_settings: RuntimeSettings) -> None:
    with pytest.raises(ValidationError):
        WorkerSettings.model_validate({**runtime_settings.worker.model_dump(), "worker_limit": 0})
