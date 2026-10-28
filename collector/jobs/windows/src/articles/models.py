from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

type DetailStage = Literal["curl_cffi", "browser_fetch", "browser_rendered", "bigkinds_api"]


class ArticleSeed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: Literal["bigkinds", "naver_news"] = "bigkinds"
    source_id: str = Field(min_length=1)
    published_on: date | None
    publisher: str | None = Field(default=None, min_length=1)
    publisher_code: str | None = Field(default=None, min_length=1)
    published_at: datetime | None = None
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


class PublisherIdentity(BaseModel):
    code: str
    name: str | None
    method: Literal["database", "domain"] = "database"


class ExtractedArticle(BaseModel):
    title: str
    text: str
    method: Literal["adaptive", "trafilatura", "snippet_dom", "bigkinds_api"]
    evidence: Evidence
    adaptive_scope: str | None = None
    publisher: PublisherIdentity | None = None
    original_published_on: date | None = None
    original_published_at: datetime | None = None
    original_modified_on: date | None = None
    original_modified_at: datetime | None = None


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
    skip_reason: Literal["no_text_body"] | None = None


class ArticleDetail(BaseModel):
    seed: ArticleSeed
    status: Literal["collected", "failed", "skipped"]
    selected_stage: DetailStage | None
    attempts: list[DetailAttempt]
    skip_reason: Literal["no_text_body"] | None = None

    @model_validator(mode="after")
    def skipped_article_requires_reason(self):
        if (self.status == "skipped") != (self.skip_reason is not None):
            raise ValueError("스킵 기사에는 본문 미확보 사유 필요")
        return self


class DetailRunSummary(BaseModel):
    run_id: str
    status: Literal["running", "completed", "partial", "failed"]
    started_at: datetime
    finished_at: datetime | None = None
    requested_count: int
    collected_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    storage: Literal["postgresql"] = "postgresql"
