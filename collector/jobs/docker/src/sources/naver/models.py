import json
import unicodedata
from datetime import date, datetime, timedelta
from hashlib import sha256
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

type Channel = Literal["news", "blog", "cafearticle"]


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    channel: Channel
    terms: tuple[str, ...] = Field(min_length=1, max_length=10)
    page_size: int = Field(default=50, ge=1, le=100)
    max_pages: int = Field(default=20, ge=1, le=20)

    @field_validator("terms")
    @classmethod
    def normalize_terms(cls, terms: tuple[str, ...]) -> tuple[str, ...]:
        normalized = {" ".join(unicodedata.normalize("NFKC", term).split()) for term in terms}
        if any(not term or len(term) > 100 or '"' in term or "|" in term for term in normalized):
            raise ValueError("검색어는 따옴표·OR 기호 없는 1~100자 문구 필요")
        return tuple(sorted(normalized))

    @property
    def query(self) -> str:
        return " | ".join(f'"{term}"' for term in self.terms)

    @property
    def stream_key(self) -> str:
        contract = {"version": 1, "channel": self.channel, "query": self.query}
        return sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()


class SearchPage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    lastBuildDate: str
    total: int = Field(ge=0)
    start: int = Field(ge=1, le=1000)
    display: int = Field(ge=0, le=100)
    items: list[dict]


class Listing(BaseModel):
    channel: Channel
    source_id: str
    title: str
    url: HttpUrl
    original_url: HttpUrl | None = None
    summary: str
    published_at: datetime | None = None
    published_on: str | None = None
    container_name: str | None = None
    content_kind: Literal["listing_excerpt"] = "listing_excerpt"


class Cursor(BaseModel):
    head_ids: list[str]
    completed_at: datetime
    run_id: UUID
    oldest_published_at: datetime | None = None
    oldest_published_on: date | None = None


class SearchSummary(BaseModel):
    run_id: UUID
    stream_key: str
    channel: Channel
    query: str
    status: Literal["running", "completed", "partial", "failed"] = "running"
    started_at: datetime
    finished_at: datetime | None = None
    pages_collected: int = 0
    retrieved_count: int = 0
    new_count: int = 0
    updated_count: int = 0
    total_count: int | None = None
    cursor_advanced: bool = False
    stop_reason: str | None = None
    error_type: str | None = None
    error_code: str | None = None
    missing_date_count: int = 0
    date_boundary_reached: bool = False


class Pagination:
    def __init__(
        self,
        request: SearchRequest,
        cursor: Cursor | None,
        overlap_pages: int,
        date_overlap_days: int = 1,
    ) -> None:
        self.request = request
        self.cursor = cursor
        self.overlap_pages = overlap_pages
        self.head_ids: list[str] = []
        self.seen: set[str] = set()
        self.pages = 0
        self.boundary_page: int | None = None
        self.total: int | None = None
        self.date_overlap = timedelta(days=date_overlap_days)
        self.oldest_published_at: datetime | None = None
        self.oldest_published_on: date | None = None
        self.previous_date: datetime | date | None = None
        self.dates_ordered = True
        self.boundary_reason: str | None = None
        self.missing_date_count = 0
        self.date_boundary_reached = False

    def date_boundary(self, items: list[Listing]) -> bool:
        if self.request.channel == "cafearticle":
            return False
        dates: list[datetime | date] = []
        for item in items:
            value = (
                item.published_at
                if self.request.channel == "news"
                else date.fromisoformat(item.published_on)
                if item.published_on
                else None
            )
            if value is None:
                self.missing_date_count += 1
                self.dates_ordered = False
                continue
            if self.previous_date is not None and value > self.previous_date:
                self.dates_ordered = False
            self.previous_date = value
            dates.append(value)
        if self.pages == 1 and dates and self.dates_ordered:
            if self.request.channel == "news":
                self.oldest_published_at = min(
                    item.published_at for item in items if item.published_at
                )
            elif self.request.channel == "blog":
                self.oldest_published_on = min(
                    date.fromisoformat(item.published_on) for item in items if item.published_on
                )
        if not self.cursor or not dates or not self.dates_ordered:
            return False
        cutoff = (
            self.cursor.oldest_published_at
            if self.request.channel == "news"
            else self.cursor.oldest_published_on
            if self.request.channel == "blog"
            else None
        )
        # 같은 날짜·지연 색인의 누락 방지를 위한 엄격한 과거 경계와 겹침 기간
        return cutoff is not None and all(value < cutoff - self.date_overlap for value in dates)

    def next_cursor(self, run_id: UUID, completed_at: datetime) -> Cursor:
        return Cursor(
            head_ids=self.head_ids,
            run_id=run_id,
            completed_at=completed_at,
            oldest_published_at=self.oldest_published_at,
            oldest_published_on=self.oldest_published_on,
        )

    def accept(self, page: SearchPage, items: list[Listing]) -> tuple[bool, str | None]:
        self.pages += 1
        ids = [item.source_id for item in items]
        if self.pages == 1:
            self.head_ids = ids
            self.total = page.total
        if not ids and page.total > page.start - 1:
            return False, "검색 건수가 있으나 빈 페이지"
        if ids and set(ids) <= self.seen:
            return False, "동일 페이지 반복"
        self.seen.update(ids)
        crossed_date = self.date_boundary(items)
        self.date_boundary_reached = crossed_date and self.dates_ordered
        if self.cursor is None:
            return True, "최신 첫 페이지로 초기화"
        if (
            self.boundary_page is None
            and self.cursor.head_ids
            and set(self.cursor.head_ids) <= self.seen
        ):
            self.boundary_page = self.pages
            self.boundary_reason = "이전 커서 및 겹침 구간 확인"
        exhausted = page.start + len(ids) > page.total
        if exhausted:
            return True, "검색 결과 끝 도달"
        if len(ids) < self.request.page_size:
            return False, "검색 건수보다 짧은 페이지"
        if self.boundary_page is not None and self.pages >= self.boundary_page + self.overlap_pages:
            return True, self.boundary_reason
        return False, None
