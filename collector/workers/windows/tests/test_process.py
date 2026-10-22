from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import psutil
import pytest

from config import RuntimeSettings
from runtime import process
from runtime.state import ProcessState, ProcessStateStore, RuntimeIdentity


def test_start_does_not_duplicate_supervisor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runtime_settings: RuntimeSettings
) -> None:
    store = ProcessStateStore(tmp_path / "state.json")
    launch = Mock(return_value=SimpleNamespace(pid=123))
    native = Mock()
    native.create_time.return_value = 456.0
    monkeypatch.setattr(process.subprocess, "Popen", launch)
    monkeypatch.setattr(process.psutil, "Process", Mock(return_value=native))
    identity = RuntimeIdentity(project="project", service="windows-worker")

    process.start_supervisor(runtime_settings, identity, store)
    process.start_supervisor(runtime_settings, identity, store)

    launch.assert_called_once()
    assert store.load() == ProcessState(pid=123, started_at=456.0)


def test_reused_pid_is_not_killed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = ProcessStateStore(tmp_path / "state.json")
    store.save(ProcessState(pid=123, started_at=456.0))
    native = Mock()
    native.create_time.return_value = 789.0
    monkeypatch.setattr(process.psutil, "Process", Mock(return_value=native))

    process.stop_supervisor(store, timeout=5)

    native.kill.assert_not_called()
    assert store.load() is None


def test_stop_kills_process_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = ProcessStateStore(tmp_path / "state.json")
    store.save(ProcessState(pid=123, started_at=456.0))
    native, child = Mock(), Mock()
    native.create_time.return_value = 456.0
    native.children.return_value = [child]
    monkeypatch.setattr(process.psutil, "Process", Mock(return_value=native))
    wait = Mock(return_value=([native, child], []))
    monkeypatch.setattr(process.psutil, "wait_procs", wait)

    process.stop_supervisor(store, timeout=5)

    native.kill.assert_called_once()
    child.kill.assert_called_once()
    wait.assert_called_once_with([native, child], timeout=5)
    assert store.load() is None


def test_failed_stop_preserves_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = ProcessStateStore(tmp_path / "state.json")
    store.save(ProcessState(pid=123, started_at=456.0))
    native = Mock()
    native.create_time.return_value = 456.0
    native.children.side_effect = psutil.AccessDenied(123)
    monkeypatch.setattr(process.psutil, "Process", Mock(return_value=native))
    with pytest.raises(psutil.AccessDenied):
        process.stop_supervisor(store, timeout=5)
    assert store.load() is not None


def test_stop_timeout_preserves_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = ProcessStateStore(tmp_path / "state.json")
    store.save(ProcessState(pid=123, started_at=456.0))
    native = Mock()
    native.create_time.return_value = 456.0
    native.children.return_value = []
    monkeypatch.setattr(process.psutil, "Process", Mock(return_value=native))
    monkeypatch.setattr(process.psutil, "wait_procs", Mock(return_value=([], [native])))

    with pytest.raises(TimeoutError):
        process.stop_supervisor(store, timeout=5)

    assert store.load() is not None


def test_dead_supervisor_is_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runtime_settings: RuntimeSettings
) -> None:
    store = ProcessStateStore(tmp_path / "state.json")
    store.save(ProcessState(pid=123, started_at=456.0))
    replacement = Mock()
    replacement.create_time.return_value = 900.0
    monkeypatch.setattr(
        process.psutil, "Process", Mock(side_effect=[psutil.NoSuchProcess(123), replacement])
    )
    monkeypatch.setattr(process.subprocess, "Popen", Mock(return_value=SimpleNamespace(pid=789)))

    process.start_supervisor(
        runtime_settings, RuntimeIdentity(project="project", service="worker"), store
    )

    assert store.load() == ProcessState(pid=789, started_at=900.0)
