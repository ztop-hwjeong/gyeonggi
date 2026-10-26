from datetime import date
from email.utils import parsedate_to_datetime
from hashlib import sha256
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import HttpUrl

from sources.naver.models import Channel, Listing


class PlainText(HTMLParser):
    def __init__(self, value: str) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.feed(value)

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def plain_text(value: str) -> str:
    return " ".join("".join(PlainText(value).parts).split())


def canonical_url(value: str) -> str:
    url = urlsplit(str(HttpUrl(value)))
    query = [
        (key, value)
        for key, value in parse_qsl(url.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in ("fbclid", "gclid")
    ]
    return urlunsplit((url.scheme, url.netloc.lower(), url.path, urlencode(sorted(query)), ""))


def normalize_item(channel: Channel, data: dict) -> Listing:
    url = canonical_url(data["link"])
    published_at = None
    published_on = None
    if channel == "news" and data.get("pubDate"):
        published_at = parsedate_to_datetime(data["pubDate"])
        if published_at.tzinfo is None:
            raise ValueError("네이버 뉴스 제공 시각에 시간대 필요")
    elif channel == "blog" and data.get("postdate"):
        value = data["postdate"]
        if len(value) != 8 or not value.isdigit():
            raise ValueError("네이버 블로그 작성일 형식 오류")
        published_on = date(int(value[:4]), int(value[4:6]), int(value[6:])).isoformat()
    original = canonical_url(data["originallink"]) if data.get("originallink") else None
    return Listing(
        channel=channel,
        source_id=sha256(url.encode()).hexdigest(),
        title=plain_text(data["title"]),
        url=HttpUrl(url),
        original_url=HttpUrl(original) if original else None,
        summary=plain_text(data["description"]),
        published_at=published_at,
        published_on=published_on,
        blog_name=plain_text(data["bloggername"])
        if channel == "blog" and data.get("bloggername")
        else None,
        blog_url=HttpUrl(canonical_url(data["bloggerlink"]))
        if channel == "blog" and data.get("bloggerlink")
        else None,
    )
