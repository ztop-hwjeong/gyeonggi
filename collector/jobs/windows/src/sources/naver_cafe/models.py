import re
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CafeSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NAVER_CAFE_", extra="ignore")

    batch_size: int = Field(default=10, ge=1, le=50)
    retry_delay_minutes: int = Field(default=60, ge=1)
    request_interval_seconds: float = Field(default=10, gt=0)
    rate_limit_timeout_seconds: float = Field(default=60, gt=0)
    max_response_bytes: int = Field(default=10_000_000, gt=0)
    error_pause_seconds: int = Field(default=900, ge=1)
    rate_limit_name: str = Field(default="naver-cafe-browser-navigation", min_length=1)
    title_similarity: float = Field(default=70, ge=0, le=100)


class CafeTarget(BaseModel):
    url: str
    article_id: int
    cafe_id: int | None = None
    cafe_slug: str | None = None

    @classmethod
    def from_url(cls, value: str) -> "CafeTarget":
        url = urlsplit(value)
        if (
            url.scheme != "https"
            or url.hostname != "cafe.naver.com"
            or url.port not in (None, 443)
            or url.username
            or url.password
        ):
            raise ValueError("HTTPS 네이버 카페 글 주소 필요")
        if match := re.fullmatch(r"/([A-Za-z0-9_-]+)/(\d+)/?", url.path):
            return cls(
                url=f"https://cafe.naver.com/{match[1]}/{match[2]}",
                cafe_slug=match[1],
                article_id=int(match[2]),
            )
        if match := re.fullmatch(r"/ca-fe/web/cafes/(\d+)/articles/(\d+)/?", url.path):
            return cls(
                url=f"https://cafe.naver.com/ca-fe/web/cafes/{match[1]}/articles/{match[2]}",
                cafe_id=int(match[1]),
                article_id=int(match[2]),
            )
        query = parse_qs(url.query)
        if url.path in ("/ArticleRead.nhn", "/ArticleRead.naver"):
            cafe_id, article_id = query.get("clubid", [""])[0], query.get("articleid", [""])[0]
            if cafe_id.isdigit() and article_id.isdigit():
                return cls.from_url(
                    f"https://cafe.naver.com/ca-fe/web/cafes/{cafe_id}/articles/{article_id}"
                )
        raise ValueError("지원하는 카페 글 URL 형식 필요")

    def matches_response(self, value: str) -> bool:
        url = urlsplit(value)
        match = re.fullmatch(r"/gw/v4/cafes/(\d+)/articles/(\d+)", url.path)
        return bool(
            url.scheme == "https"
            and url.hostname == "article.cafe.naver.com"
            and match
            and int(match[2]) == self.article_id
            and (self.cafe_id is None or int(match[1]) == self.cafe_id)
        )
