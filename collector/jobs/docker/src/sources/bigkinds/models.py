from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class ListCollectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    search_key: str = Field(min_length=1)
    start_date: date
    end_date: date
    # 실제 조회로 확인한 BigKinds 최대 페이지 크기
    page_size: int = Field(default=100, ge=1, le=100)
    max_pages: int | None = Field(default=None, ge=1)
    provider_codes: tuple[Annotated[str, Field(pattern=r"^[0-9]{8}$")], ...] = ()

    @model_validator(mode="after")
    def validate_period(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("종료일은 시작일 이후 필요")
        return self


class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    total_count: int = Field(alias="totalCount", ge=0)
    result_list: list[dict] = Field(alias="resultList")


class ArticleListing(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: Literal["bigkinds"] = "bigkinds"
    source_id: str = Field(min_length=1)
    published_on: date
    publisher: str = Field(min_length=1)
    title: str = Field(min_length=1)
    original_url: HttpUrl | None
    summary: str
    content_kind: Literal["listing_excerpt"] = "listing_excerpt"


class StoredResponse(BaseModel):
    page_number: int
    body_path: Path
    metadata_path: Path


class NormalizedPage(BaseModel):
    page_number: int
    total_count: int
    article_count: int
    source_ids: tuple[str, ...]
    items_path: Path


class CollectionSummary(BaseModel):
    run_id: str
    status: Literal["running", "completed", "partial", "failed"]
    started_at: datetime
    finished_at: datetime | None = None
    request: ListCollectionRequest
    impersonate: str
    output_directory: Path
    pages_collected: int = 0
    initial_total_count: int | None = None
    latest_total_count: int | None = None
    retrieved_count: int = 0
    unique_count: int = 0
    duplicate_count: int = 0
    stop_reason: str | None = None
    error_type: str | None = None
