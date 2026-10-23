import json
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any

from collector_http.client import AccessRestrictedError, UnexpectedResponseError
from pydantic import HttpUrl

from sources.bigkinds.models import ArticleListing, SearchResponse


class _PlainText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def plain_text(value: str) -> str:
    parser = _PlainText()
    parser.feed(value)
    parser.close()
    return "".join(parser.parts).strip()


def parse_search_response(body: bytes) -> SearchResponse:
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError) as error:
        raise UnexpectedResponseError("빅카인즈 검색 JSON 응답 필요") from error
    if not isinstance(data, dict) or data.get("success") is False:
        raise UnexpectedResponseError("빅카인즈 검색 실패 응답")
    if data.get("loginRequired") is True:
        raise AccessRestrictedError("빅카인즈 로그인 필요")
    return SearchResponse.model_validate(data)


def normalize_listing(item: dict[str, Any]) -> ArticleListing:
    original_url = unescape((item.get("PROVIDER_LINK_PAGE") or "").strip())
    # 실제 응답에 포함된 스킴 없는 원문 주소의 HTTPS 정규화
    if original_url.startswith("www."):
        original_url = "https://" + original_url
    elif original_url.startswith("//"):
        original_url = "https:" + original_url
    return ArticleListing(
        source_id=item["NEWS_ID"],
        published_on=datetime.strptime(item["DATE"], "%Y%m%d").date(),
        publisher=plain_text(item["PROVIDER"]),
        title=plain_text(item["TITLE"]),
        original_url=HttpUrl(original_url) if original_url else None,
        summary=plain_text(item["CONTENT"]),
    )
