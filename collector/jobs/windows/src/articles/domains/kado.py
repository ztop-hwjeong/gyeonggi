import re
from urllib.parse import parse_qs, urlsplit

from lxml import html
from scrapling import Selector

from articles.domains.base import DomainBody
from articles.matching import normalized_text, verify_article
from articles.models import ArticleSeed
from config import ExtractionSettings

_COPYRIGHT_SUFFIX = re.compile(
    r"\s*저작권자\s*ⓒ\s*강원도민일보\(https://www\.kado\.net\)\s*무단전재 및 재배포금지\s*$"
)
_SHORT_BODY_REASONS = frozenset({"본문 길이 부족", "목록 요약보다 충분한 본문 필요"})


def _article_id(url: str) -> str | None:
    return parse_qs(urlsplit(url).query).get("idxno", [None])[0]


def _photo_only_caption(body: html.HtmlElement) -> str | None:
    children = [child for child in body if child.tag not in {"script", "style", "template"}]
    if len(children) != 1 or children[0].tag != "figure":
        return None
    captions = children[0].xpath("./figcaption")
    if len(captions) != 1:
        return None
    return captions[0].text_content().strip() or None


def _has_verified_short_photo_body(
    seed: ArticleSeed, title: str, caption: str, url: str, settings: ExtractionSettings, reason: str
) -> bool:
    original_url = str(seed.original_url or "")
    summary = _COPYRIGHT_SUFFIX.sub("", seed.summary)
    reason_parts = frozenset(part.strip() for part in reason.split(";") if part.strip())
    return (
        urlsplit(url).hostname in KadoBodyPolicy.hosts
        and normalized_text(title) == normalized_text(seed.title)
        and _article_id(original_url) is not None
        and _article_id(original_url) == _article_id(url)
        and len(normalized_text(caption)) >= settings.min_summary_chars
        and normalized_text(summary) == normalized_text(caption)
        and bool(reason_parts)
        and reason_parts.issubset(_SHORT_BODY_REASONS)
    )


class KadoBodyPolicy:
    hosts: tuple[str, ...] = ("kado.net", "www.kado.net")

    def has_no_text_body(
        self, seed: ArticleSeed, page: Selector, title: str, url: str, markup: str
    ) -> bool:
        return False

    def extract_body(
        self,
        seed: ArticleSeed,
        page: Selector,
        title: str,
        url: str,
        markup: str,
        settings: ExtractionSettings,
    ) -> DomainBody | None:
        tree = html.fromstring(markup)
        nodes = tree.xpath("//*[@id='article-view-content-div' and @itemprop='articleBody']")
        if len(nodes) != 1:
            return None
        body = nodes[0]
        for node in body.xpath(".//script | .//style | .//template"):
            node.drop_tree()
        caption = _photo_only_caption(body)
        text = caption or body.text_content().strip()
        evidence = verify_article(seed, title, text, settings)
        if caption and _has_verified_short_photo_body(
            seed, title, caption, url, settings, evidence.reason
        ):
            evidence = evidence.model_copy(
                update={"verified": True, "reason": "강원도민일보 사진 캡션·제목·원문 ID 일치"}
            )
        return DomainBody(text=text, evidence=evidence)
