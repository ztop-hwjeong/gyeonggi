from datetime import UTC, datetime, timedelta
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

type Stage = Literal["curl_cffi", "browser_fetch", "bigkinds_api"]
type RunState = Literal[
    "SCHEDULED",
    "PENDING",
    "RUNNING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "CRASHED",
    "PAUSED",
    "CANCELLING",
]


class Window(BaseModel):
    model_config = ConfigDict(extra="forbid")

    since: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC) - timedelta(days=1))
    until: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        if not self.since < self.until:
            raise ValueError("종료 시각은 시작 시각 이후 필요")
        if self.until - self.since > timedelta(days=31):
            raise ValueError("한 번에 최대 31일 조회 가능")
        return self


class PageQuery(Window):
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class RunQuery(PageQuery):
    state: RunState | None = None


class ErrorQuery(PageQuery):
    run_id: UUID | None = None
    stage: Stage | None = None
    recovered: bool | None = None


class CollectionProgress(BaseModel):
    status: Literal["running", "completed", "partial", "failed"]
    requested_count: int
    collected_count: int
    failed_count: int
    started_at: datetime
    finished_at: datetime | None


class RunStateInfo(BaseModel):
    type: RunState
    name: str
    message: str | None = None
    timestamp: datetime


class RunInfo(BaseModel):
    id: UUID
    flow_id: UUID
    flow_name: str
    name: str
    state: RunStateInfo | None
    expected_start_time: datetime | None
    start_time: datetime | None
    end_time: datetime | None
    estimated_run_time: float
    collection: CollectionProgress | None = None


class RunPage(BaseModel):
    items: list[RunInfo]
    total: int
    limit: int
    offset: int


class WorkerInfo(BaseModel):
    id: UUID
    name: str
    status: Literal["ONLINE", "OFFLINE"]
    last_heartbeat_time: datetime | None
    heartbeat_interval_seconds: int | None


class PoolInfo(BaseModel):
    name: str
    type: str
    is_paused: bool
    status: str
    workers: list[WorkerInfo]


class WorkerSnapshot(BaseModel):
    observed_at: datetime
    pools: list[PoolInfo]


class AttemptCount(BaseModel):
    stage: Stage
    status: Literal["accepted", "rejected", "failed", "skipped"]
    count: int


class HttpErrorCount(BaseModel):
    stage: Stage
    status_code: int
    count: int


class CollectionMetrics(BaseModel):
    scope: Literal["article_details"] = "article_details"
    since: datetime
    until: datetime
    observed_at: datetime
    run_status_counts: dict[str, int]
    requested_articles: int
    processed_articles: int
    collected_articles: int
    failed_articles: int
    success_rate: float | None
    attempts: list[AttemptCount]
    http_errors: list[HttpErrorCount]
    raw_response_count: int
    raw_response_bytes: int
    last_completed_run_at: datetime | None


class CollectionError(BaseModel):
    run_id: UUID
    source_id: str
    stage: Stage
    status: Literal["rejected", "failed"]
    reason: str
    recovered: bool
    run_created_at: datetime
    http_status_codes: list[int]


class ErrorPage(BaseModel):
    items: list[CollectionError]
    total: int
    limit: int
    offset: int


class ArticleStatus(BaseModel):
    source_id: str
    publisher: str
    title: str
    status: Literal["collected", "failed"]
    selected_stage: Stage | None


class ArticlePage(BaseModel):
    items: list[ArticleStatus]
    total: int
    limit: int
    offset: int
