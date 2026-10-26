from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class EventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)
    occurred_at: AwareDatetime
    tag_ids: list[str] = Field(default_factory=list, max_length=100)
    folder_ids: list[UUID] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def distinct_targets(self) -> Self:
        if len(self.tag_ids) != len(set(self.tag_ids)):
            raise ValueError("태그 중복")
        if len(self.folder_ids) != len(set(self.folder_ids)):
            raise ValueError("폴더 중복")
        return self


class EventUpdate(EventCreate):
    version: int = Field(ge=1)


class EventTargetInfo(BaseModel):
    kind: Literal["tag", "folder"]
    id: str
    name: str


class EventInfo(BaseModel):
    id: UUID
    name: str
    occurred_at: datetime
    version: int
    targets: list[EventTargetInfo]
    created_at: datetime
    updated_at: datetime


class EventQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    q: str = Field(default="", max_length=100)
    occurred_from: AwareDatetime | None = None
    occurred_until: AwareDatetime | None = None
    tag_id: str | None = None
    folder_id: UUID | None = None

    @model_validator(mode="after")
    def valid_range(self) -> Self:
        if (
            self.occurred_from is not None
            and self.occurred_until is not None
            and self.occurred_from > self.occurred_until
        ):
            raise ValueError("조회 시작이 종료보다 늦음")
        return self
