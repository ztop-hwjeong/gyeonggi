from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

type DetailStage = Literal["curl_cffi", "browser_fetch", "browser_rendered", "bigkinds_api"]


class ArticleSeed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: Literal["bigkinds"] = "bigkinds"
    source_id: str = Field(min_length=1)
    published_on: date | None
    publisher: str = Field(min_length=1)
    title: str = Field(min_length=1)
    original_url: HttpUrl | None
    summary: str
    content_kind: Literal["listing_excerpt"] = "listing_excerpt"


class Evidence(BaseModel):
    verified: bool
    title_score: float
    snippet_scores: list[float]
    snippet_match_fraction: float
    body_chars: int
    reason: str
    summary_score: float | None = None


class ExtractedArticle(BaseModel):
    title: str
    text: str
    method: Literal["adaptive", "trafilatura", "snippet_dom", "bigkinds_api"]
    evidence: Evidence
    adaptive_scope: str | None = None
    published_at: datetime | None = None


class FetchSnapshot(BaseModel):
    url: str
    status_code: int
    content_type: str
    response_id: UUID
    sha256: str
    received_at: datetime
    retry_after: str | None = None


class DetailAttempt(BaseModel):
    stage: DetailStage
    status: Literal["accepted", "rejected", "failed", "skipped"]
    reason: str
    snapshots: list[FetchSnapshot] = Field(default_factory=list)
    extraction: ExtractedArticle | None = None


class ArticleDetail(BaseModel):
    seed: ArticleSeed
    status: Literal["collected", "failed"]
    selected_stage: DetailStage | None
    attempts: list[DetailAttempt]


class DetailRunSummary(BaseModel):
    run_id: str
    status: Literal["running", "completed", "partial", "failed"]
    started_at: datetime
    finished_at: datetime | None = None
    requested_count: int
    collected_count: int = 0
    failed_count: int = 0
    storage: Literal["postgresql"] = "postgresql"
