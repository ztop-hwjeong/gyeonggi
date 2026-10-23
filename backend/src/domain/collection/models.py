from datetime import date, datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

type SourceCode = Literal["bigkinds", "naver_news", "naver_blog", "naver_cafearticle"]
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
        supports_backfill=False,
        description="최신순 검색과 커서 이후 증분 수집",
    ),
    SourceInfo(
        code="naver_blog",
        name="네이버 블로그",
        supports_backfill=False,
        description="최신순 검색과 커서 이후 증분 수집",
    ),
    SourceInfo(
        code="naver_cafearticle",
        name="네이버 카페",
        supports_backfill=False,
        description="공개 검색 목록과 커서 이후 증분 수집",
    ),
)


class RuleDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    terms: tuple[Annotated[str, Field(min_length=1, max_length=100)], ...] = Field(
        min_length=1, max_length=10
    )
    sources: tuple[SourceCode, ...] = Field(min_length=1, max_length=4)
    enabled: bool = False
    interval_minutes: int = Field(default=15, ge=15, le=1440)

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
        if (self.end_date - self.start_date).days > 366:
            raise ValueError("한 번에 최대 1년까지 수집 요청 가능")
        return self


class RunCreate(DateRange):
    rule_id: UUID
    version: int = Field(ge=1)
    source: SourceCode
    mode: Literal["incremental", "backfill"]

    @model_validator(mode="after")
    def valid_capability(self) -> Self:
        if self.mode == "backfill" and self.source != "bigkinds":
            raise ValueError("네이버 검색 API는 기간 지정 과거 수집을 지원하지 않음")
        return self


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


class Pagination(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(default=30, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class RulePage(BaseModel):
    items: list[RuleInfo]
    total: int


class RequestQuery(Pagination):
    rule_id: UUID | None = None


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
