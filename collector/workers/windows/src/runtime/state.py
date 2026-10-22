from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class RuntimeIdentity(BaseModel):
    project: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
    service: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")

    @property
    def name(self) -> str:
        return f"{self.project}-{self.service}"


class ProcessState(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    pid: int = Field(gt=0)
    started_at: float = Field(gt=0)


class ProcessStateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> ProcessState | None:
        if not self.path.exists():
            return None
        return ProcessState.model_validate_json(self.path.read_text(encoding="utf-8"))

    def save(self, state: ProcessState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(state.model_dump_json(), encoding="utf-8")
        temporary.replace(self.path)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
