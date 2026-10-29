from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class BlogSeed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["naver_blog"]
    source_id: str
    url: HttpUrl
    title: str
    summary: str = ""
    published_on: date | None = None


class ExtractedBlog(BaseModel):
    title: str
    body: str = Field(min_length=10)
    original_published_on: date | None = None
    original_published_at: datetime | None = None
