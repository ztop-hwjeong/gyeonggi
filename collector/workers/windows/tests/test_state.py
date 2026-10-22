from pathlib import Path

import pytest
from pydantic import ValidationError

from runtime.state import ProcessState, ProcessStateStore, RuntimeIdentity


@pytest.mark.parametrize(
    "content", ["{", '{"pid":0,"started_at":1}', '{"pid":"123","started_at":1}']
)
def test_invalid_state_is_rejected(tmp_path: Path, content: str) -> None:
    path = tmp_path / "state.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValidationError):
        ProcessStateStore(path).load()


def test_state_replacement_is_readable(tmp_path: Path) -> None:
    store = ProcessStateStore(tmp_path / "runtime" / "state.json")
    store.save(ProcessState(pid=123, started_at=456.0))
    store.save(ProcessState(pid=789, started_at=900.0))
    assert store.load() == ProcessState(pid=789, started_at=900.0)
    assert not store.path.with_suffix(".tmp").exists()


def test_identity_cannot_escape_runtime_directory() -> None:
    with pytest.raises(ValidationError):
        RuntimeIdentity(project="../../other", service="worker")
