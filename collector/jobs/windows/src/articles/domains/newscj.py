from urllib.parse import parse_qs, urlsplit

from lxml import html
from scrapling import Selector

from articles.domains.base import DomainBody
from articles.matching import normalized_text, verify_article
from articles.models import ArticleSeed
from config import ExtractionSettings


def _article_id(url: str) -> str | None:
    return parse_qs(urlsplit(url).query).get("idxno", [None])[0]


def _has_verified_short_photo_body(
    seed: ArticleSeed, title: str, text: str, url: str, settings: ExtractionSettings, reason: str
) -> bool:
    original_url = str(seed.original_url or "")
    return (
        urlsplit(url).hostname in NewscjBodyPolicy.hosts
        and seed.title.lstrip("\u200b \t\r\n").startswith("[포토]")
        and normalized_text(title) == normalized_text(seed.title)
        and len(normalized_text(text)) >= settings.min_summary_chars
        and _article_id(original_url) is not None
        and _article_id(original_url) == _article_id(url)
        and reason == "본문 길이 부족"
    )


class NewscjBodyPolicy:
    hosts: tuple[str, ...] = ("newscj.com", "www.newscj.com")

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
        nodes = tree.xpath("//article[@id='article-view-content-div' and @itemprop='articleBody']")
        if len(nodes) != 1:
            return None
        body = nodes[0]
        for node in body.xpath(
            ".//script | .//style | .//template | "
            ".//div["
            "contains(concat(' ', normalize-space(@class), ' '), ' raw-html ') and "
            ".//*[@id='btn-en-article']"
            "] | "
            ".//*[contains(concat(' ', normalize-space(@class), ' '), ' ad-template ')]"
        ):
            node.drop_tree()
        text = body.text_content().strip()
        evidence = verify_article(seed, title, text, settings)
        if _has_verified_short_photo_body(seed, title, text, url, settings, evidence.reason):
            evidence = evidence.model_copy(
                update={"verified": True, "reason": "천지일보 포토 제목·요약·원문 ID 일치"}
            )
        return DomainBody(text=text, evidence=evidence)
