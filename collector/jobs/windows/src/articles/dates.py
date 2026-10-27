import json
import re
from collections.abc import Iterable
from datetime import date, datetime
from zoneinfo import ZoneInfo

from lxml import html

KST = ZoneInfo("Asia/Seoul")
_DATE_ONLY = re.compile(r"^(\d{4})[./-](\d{1,2})[./-](\d{1,2})\.?$")
_KOREAN_DATETIME = re.compile(
    r"^(\d{4})[./-](\d{1,2})[./-](\d{1,2})\.?\s+(\d{1,2}):(\d{2})(?::(\d{2}))?$"
)
_PAGE_DATE = re.compile(r"\d{4}[./-]\d{1,2}[./-]\d{1,2}\.?")


def parse_source_date(value: object) -> tuple[date | None, datetime | None]:
    """원문 표기 날짜와 시각을 정밀도 손실 없이 분리."""
    if not isinstance(value, str) or not (raw := " ".join(value.split())):
        return None, None
    if matched := _DATE_ONLY.fullmatch(raw):
        try:
            return date(*map(int, matched.groups())), None
        except ValueError:
            return None, None
    if matched := _KOREAN_DATETIME.fullmatch(raw):
        try:
            year, month, day, hour, minute, second = map(int, matched.groups(default="0"))
            parsed = datetime(year, month, day, hour, minute, second, tzinfo=KST)
        except ValueError:
            return None, None
        return parsed.date(), parsed
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None, None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KST)
    return parsed.astimezone(KST).date(), parsed


def _article_json_values(value: object, keys: set[str]) -> Iterable[str]:
    if isinstance(value, dict):
        types = value.get("@type", [])
        if isinstance(types, str):
            types = [types]
        is_article = isinstance(types, list) and any(
            isinstance(item, str)
            and item.casefold() in {"article", "newsarticle", "reportagenewsarticle", "blogposting"}
            for item in types
        )
        for key, child in value.items():
            if is_article and key.casefold() in keys and isinstance(child, str):
                yield child
            yield from _article_json_values(child, keys)
    elif isinstance(value, list):
        for child in value:
            yield from _article_json_values(child, keys)


def _metadata_values(tree: html.HtmlElement, names: tuple[str, ...]) -> Iterable[str]:
    names_lower = {name.casefold() for name in names}
    for node in tree.xpath("//meta[@content]"):
        label = (node.get("property") or node.get("name") or node.get("itemprop") or "").casefold()
        if label in names_lower:
            yield node.get("content", "")
    for node in tree.xpath("//*[@itemprop]"):
        if (node.get("itemprop") or "").casefold() in names_lower:
            yield node.get("content") or node.get("datetime") or node.text_content()


def _trafilatura_date(markup: str, value: str | None) -> str | None:
    parsed_on, _ = parse_source_date(value)
    if parsed_on is None:
        return None
    visible_markup = re.sub(
        r"<script\b[^>]*>.*?</script\s*>", "", markup, flags=re.IGNORECASE | re.DOTALL
    )
    for matched in _PAGE_DATE.findall(visible_markup):
        page_on, _ = parse_source_date(matched)
        if page_on == parsed_on:
            return matched
    return None


def extract_source_dates(
    markup: str, trafilatura_date: str | None
) -> tuple[date | None, datetime | None, date | None, datetime | None]:
    """JSON-LD와 메타데이터를 우선해 원문 발행·수정 시각 추출."""
    try:
        tree = html.fromstring(markup)
    except (ValueError, TypeError):
        return parse_source_date(trafilatura_date) + (None, None)
    published: list[str] = []
    modified: list[str] = []
    for node in tree.xpath("//script[@type='application/ld+json']"):
        try:
            payload = json.loads(node.text or "")
        except json.JSONDecodeError:
            continue
        published.extend(_article_json_values(payload, {"datepublished"}))
        modified.extend(_article_json_values(payload, {"datemodified"}))
    published.extend(
        _metadata_values(
            tree,
            ("article:published_time", "datepublished", "publishdate", "pubdate"),
        )
    )
    modified.extend(
        _metadata_values(tree, ("article:modified_time", "datemodified", "lastmodified"))
    )

    def first(values: Iterable[str]) -> tuple[date | None, datetime | None]:
        parsed_values = [parse_source_date(value) for value in values]
        for parsed_on, parsed_at in parsed_values:
            if parsed_at is not None:
                return parsed_on, parsed_at
        for parsed_on, _ in parsed_values:
            if parsed_on is not None:
                return parsed_on, None
        return None, None

    trafilatura_value = _trafilatura_date(markup, trafilatura_date)
    published_on, published_at = first([*published, trafilatura_value or ""])
    modified_on, modified_at = first(modified)
    return published_on, published_at, modified_on, modified_at
