from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def normalize_label(value: str) -> str:
    return " ".join(value.casefold().split())


class Topic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,39}$")
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=400)
    synonyms: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("name")
    @classmethod
    def no_comma_name(cls, value: str) -> str:
        if "," in value or not value.strip():
            raise ValueError("주제명 쉼표·공백만 사용 불가")
        return value.strip()


class TopicInfo(BaseModel):
    id: str
    name: str
    description: str
    synonyms: list[str]
    version: int
    created_at: datetime
    updated_at: datetime


class TopicUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(max_length=400)
    synonyms: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("name")
    @classmethod
    def no_comma_name(cls, value: str) -> str:
        if "," in value or not value.strip():
            raise ValueError("주제명 쉼표·공백만 사용 불가")
        return value.strip()


class TopicMerge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,39}$")


class ArticleTopicOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["include", "exclude", "release"]


class CanonicalArticleTopicLink(BaseModel):
    article_id: UUID
    topic_id: str
    origin: Literal["ai", "manual_include", "manual_exclude", "conflict"]


class AnalysisRunInfo(BaseModel):
    id: UUID
    article_id: UUID
    source: str
    source_id: str
    content_hash: str
    model: str
    prompt: str | None
    prompt_hash: str | None
    status: Literal["queued", "running", "completed", "failed"]
    catalog_snapshot: dict
    model_draft: dict | None
    applied_result: dict | None
    usage: dict
    error: str | None
    lease_expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AnalysisAttemptInfo(BaseModel):
    id: int
    run_id: UUID
    prefect_flow_run_id: UUID | None
    prefect_task_run_id: UUID | None
    status: Literal["running", "completed", "failed"]
    error: str | None
    usage: dict
    model_draft: dict | None
    started_at: datetime
    finished_at: datetime | None
