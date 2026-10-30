from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


def _terms(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


class ReportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_id: UUID
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    keyword_terms: list[Annotated[str, Field(min_length=1, max_length=100)]] | None = Field(
        default=None, max_length=100
    )
    keywords_automatic: bool = True
    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None

    @field_validator("keyword_terms")
    @classmethod
    def normalize_terms(cls, value: list[str] | None) -> list[str] | None:
        return _terms(value)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("보고서 제목 공백만 사용 불가")
        return value.strip() if value else value

    @model_validator(mode="after")
    def valid_period(self) -> "ReportCreate":
        if self.start_at is not None and self.end_at is not None and self.start_at >= self.end_at:
            raise ValueError("보고서 종료 시각은 시작 시각 이후 필요")
        return self


class ReportUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    keyword_terms: list[Annotated[str, Field(min_length=1, max_length=100)]] | None = Field(
        default=None, max_length=100
    )
    keywords_automatic: bool | None = None
    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None
    relevance_criteria: str | None = Field(default=None, max_length=4000)

    @field_validator("keyword_terms")
    @classmethod
    def normalize_terms(cls, value: list[str] | None) -> list[str] | None:
        return _terms(value)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("보고서 제목 공백만 사용 불가")
        return value.strip() if value else value

    @model_validator(mode="after")
    def valid_period(self) -> "ReportUpdate":
        if "title" in self.model_fields_set and self.title is None:
            raise ValueError("보고서 제목 필요")
        if "description" in self.model_fields_set and self.description is None:
            raise ValueError("보고서 설명은 null 사용 불가")
        if "relevance_criteria" in self.model_fields_set and self.relevance_criteria is None:
            raise ValueError("관련성 선별 기준은 null 사용 불가")
        if self.start_at is not None and self.end_at is not None and self.start_at >= self.end_at:
            raise ValueError("보고서 종료 시각은 시작 시각 이후 필요")
        return self


class ReportDecisionWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["include", "exclude", "release"]
    reason: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def exclusion_reason(self) -> "ReportDecisionWrite":
        if self.decision == "exclude" and not self.reason.strip():
            raise ValueError("제외 사유 필요")
        return self


class ReportBulkDecision(ReportDecisionWrite):
    article_ids: list[UUID] = Field(min_length=1, max_length=200)


class ReportInfo(BaseModel):
    id: UUID
    target_id: UUID
    target_kind: Literal["regular", "current_issue"]
    title: str
    description: str
    relevance_criteria: str
    keyword_terms: list[str]
    keywords_automatic: bool
    is_default: bool
    start_at: datetime | None
    end_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime


class ReportArticle(BaseModel):
    id: UUID
    title: str
    summary: str
    publisher: str | None
    original_published_at: datetime | None
    content_preview: str
    is_keyword_match: bool
    matched_keywords: list[str]
    report_decision: Literal["include", "exclude"] | None
    report_decision_reason: str | None = None
    ai_status: Literal[
        "unjudged", "queued", "submitted", "running", "completed", "failed", "outdated"
    ] = "unjudged"
    ai_relevance: Literal["related", "unrelated", "uncertain"] | None = None
    ai_reason: str | None = None
    ai_evidence: list[str] = Field(default_factory=list)


class RelevanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["selected", "filtered"]
    article_ids: list[UUID] = Field(default_factory=list, max_length=200)
    mode: Literal["unjudged", "failed", "refresh"] = "unjudged"
    keyword_match: Literal["all", "matched", "unmatched"] = "all"
    inclusion: Literal["all", "unreviewed", "included", "excluded"] = "all"
    ai_relevance: Literal[
        "all", "unjudged", "related", "unrelated", "uncertain", "failed", "pending", "outdated"
    ] = "all"
    q: str | None = Field(default=None, max_length=100)
    preview_fingerprint: str | None = Field(default=None, min_length=64, max_length=64)


class RelevancePreview(BaseModel):
    eligible: int
    skipped_no_body: int
    skipped_excluded: int
    skipped_current: int
    pending: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_cost_usd: float = Field(ge=0)
    model: str = "gpt-6-luna"
    fingerprint: str


class RelevanceEnqueue(BaseModel):
    batch_id: UUID
    queued: int
    reused: int
    message: str | None = None


class ReportArticleDetail(ReportArticle):
    body: str | None
    content_hash: str | None
    ai_error: str | None = None


class ReportArticlePage(BaseModel):
    items: list[ReportArticle]
    total: int
    filtered_total: int
    matched: int
    unmatched: int
    included: int
    excluded: int
    unreviewed: int
    ai_unjudged: int
    ai_related: int
    ai_unrelated: int
    ai_uncertain: int
    ai_pending: int
    ai_failed: int
    ai_outdated: int
