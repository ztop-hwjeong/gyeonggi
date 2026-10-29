from datetime import date, datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

type SourceCode = Literal["bigkinds", "naver_news", "naver_blog"]
type MaterialKind = Literal["news", "blog"]
type RequestMode = Literal["preview", "incremental", "backfill"]


class SourceInfo(BaseModel):
    code: SourceCode
    name: str
    supports_backfill: bool
    description: str


SOURCES = (
    SourceInfo(
        code="bigkinds",
        name="빅카인즈",
        supports_backfill=True,
        description="기간을 지정한 언론 보도 검색",
    ),
    SourceInfo(
        code="naver_news",
        name="네이버 뉴스",
        supports_backfill=True,
        description="최신순 검색의 날짜 경계까지 기간 보충 수집",
    ),
    SourceInfo(
        code="naver_blog",
        name="네이버 블로그",
        supports_backfill=True,
        description="최신순 검색의 작성일 경계까지 기간 보충 수집",
    ),
)


class RuleDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    terms: tuple[Annotated[str, Field(min_length=1, max_length=100)], ...] = Field(
        min_length=1, max_length=10
    )
    sources: tuple[SourceCode, ...] = Field(min_length=1, max_length=3)
    enabled: bool = False

    @field_validator("terms")
    @classmethod
    def normalize_terms(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(dict.fromkeys(" ".join(value.split()) for value in values))
        if any(
            not value or any(symbol in value for symbol in ('"', "|", "\n")) for value in normalized
        ):
            raise ValueError("검색어는 따옴표와 OR 기호 없는 문구 필요")
        return normalized

    @field_validator("sources")
    @classmethod
    def unique_sources(cls, values: tuple[SourceCode, ...]) -> tuple[SourceCode, ...]:
        return tuple(dict.fromkeys(values))


class RuleUpdate(RuleDefinition):
    version: int = Field(ge=1)


class RuleInfo(BaseModel):
    id: UUID
    version: int
    definition: RuleDefinition
    created_at: datetime
    updated_at: datetime


class RuleVersion(BaseModel):
    version: int
    definition: RuleDefinition
    created_at: datetime


class DateRange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def valid_dates(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("종료일은 시작일 이후 필요")
        return self


class RunCreate(DateRange):
    rule_id: UUID
    version: int = Field(ge=1)
    source: SourceCode
    mode: Literal["incremental", "backfill"]


class PreviewCreate(DateRange):
    definition: RuleDefinition
    source: SourceCode

    @model_validator(mode="after")
    def selected_source(self) -> Self:
        if self.source not in self.definition.sources:
            raise ValueError("검색 규칙에 등록한 채널 필요")
        return self


class RequestInfo(BaseModel):
    id: UUID
    rule_id: UUID | None
    rule_version: int | None
    source: SourceCode
    mode: RequestMode
    definition: RuleDefinition
    start_date: date
    end_date: date
    status: str
    flow_run_id: UUID | None
    summary: dict
    error: str | None
    created_at: datetime
    updated_at: datetime
    reviewed_at: datetime | None = None


class RequestReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewed: bool


class Pagination(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(default=30, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class RulePage(BaseModel):
    items: list[RuleInfo]
    total: int


class RuleQuery(Pagination):
    q: str = Field(default="", max_length=100)
    enabled: bool | None = None


class RequestQuery(Pagination):
    rule_id: UUID | None = None
    source: SourceCode | None = None
    mode: RequestMode | None = None
    status: (
        Literal[
            "queued",
            "submitted",
            "running",
            "completed",
            "partial",
            "failed",
            "cancelled",
            "cancelling",
            "attention",
            "active",
        ]
        | None
    ) = None


class RequestPage(BaseModel):
    items: list[RequestInfo]
    total: int


class ResultItem(BaseModel):
    source_id: str
    title: str
    summary: str
    publisher: str | None = None
    url: str | None = None
    original_url: str | None = None
    published_at: datetime | None = None
    published_on: str | None = None


class ResultPage(BaseModel):
    items: list[ResultItem]
    total: int


class ArticleQuery(Pagination):
    source: SourceCode | None = None
    q: str = Field(default="", max_length=100)
    inclusion: Literal["all", "included", "excluded"] = "all"
    target_id: UUID | None = None
    tag_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]{0,39}$")
    folder_id: UUID | None = None
    include_descendants: bool = True
    unfiled: bool = False

    @model_validator(mode="after")
    def one_tag_scope(self) -> Self:
        if sum((self.tag_id is not None, self.folder_id is not None, self.unfiled)) > 1:
            raise ValueError("태그, 폴더, 미분류 중 하나만 선택")
        return self


class MaterialQuery(Pagination):
    kind: MaterialKind | None = None
    group: Literal["news", "posts"] | None = None
    source: SourceCode | None = None
    q: str = Field(default="", max_length=100)
    tag_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]{0,39}$")
    folder_id: UUID | None = None
    include_descendants: bool = True
    unfiled: bool = False

    @model_validator(mode="after")
    def one_kind_scope(self) -> Self:
        if self.kind is not None and self.group is not None:
            raise ValueError("자료 유형 또는 자료 그룹 중 하나만 선택")
        if sum((self.tag_id is not None, self.folder_id is not None, self.unfiled)) > 1:
            raise ValueError("태그, 폴더, 미분류 중 하나만 선택")
        return self


class ArticleSource(BaseModel):
    source: SourceCode
    source_id: str
    url: str | None
    original_url: str | None
    canonical_url: str | None
    published_at: datetime | None = None
    first_seen_at: datetime


class StoredMaterial(BaseModel):
    id: UUID
    kind: MaterialKind
    title: str
    summary: str
    publisher: str | None
    blog_name: str | None
    blog_url: str | None
    published_on: date | None
    published_at: datetime | None
    sources: list[ArticleSource]
    content_preview: str
    has_body: bool
    body_skip_reason: str | None = None
    sentiment: Literal["긍정", "중립", "부정"] | None = None
    mixed_sentiment: bool | None = None
    sentiment_reason: str | None = None
    sentiment_origin: Literal["ai", "manual"] | None = None


class StoredMaterialDetail(StoredMaterial):
    body: str | None
    content_hash: str | None
    body_collected_at: datetime | None
    original_published_on: date | None = None
    original_published_at: datetime | None = None
    original_modified_on: date | None = None
    original_modified_at: datetime | None = None


class StoredMaterialPage(BaseModel):
    items: list[StoredMaterial]
    total: int


class StoredArticle(BaseModel):
    id: UUID
    title: str
    summary: str
    publisher: str | None
    published_on: date | None
    published_at: datetime | None
    sources: list[ArticleSource]
    inclusion: Literal["include", "exclude"]
    inclusion_reason: str | None
    content_preview: str
    has_body: bool
    body_skip_reason: Literal["no_text_body"] | None = None
    sentiment: Literal["긍정", "중립", "부정"] | None = None
    mixed_sentiment: bool | None = None
    sentiment_reason: str | None = None
    sentiment_origin: Literal["ai", "manual"] | None = None


class StoredArticlePage(BaseModel):
    items: list[StoredArticle]
    total: int


class StoredArticleDetail(StoredArticle):
    body: str | None
    content_hash: str | None
    body_collected_at: datetime | None
    original_published_on: date | None = None
    original_published_at: datetime | None = None
    original_modified_on: date | None = None
    original_modified_at: datetime | None = None


class DailyCount(BaseModel):
    day: date
    count: int


class Overview(BaseModel):
    total_items: int
    kind_counts: dict[MaterialKind, int]
    active_rules: int
    total_rules: int
    queued_requests: int
    failed_requests: int
    partial_requests: int
    daily_counts: list[DailyCount]
    source_counts: dict[str, int]
    body_skipped_articles: int
