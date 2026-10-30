import re
from urllib.parse import urlsplit

from lxml import html
from scrapling import Selector

from articles.domains.base import DomainBody
from articles.matching import normalized_text, verify_article
from articles.models import ArticleSeed
from config import ExtractionSettings

_PHOTO_CREDIT = re.compile(r"^\s*\[사진\s*=\s*[^\]]+\]\s*")


def has_verified_official_photo_body(
    seed: ArticleSeed, title: str, text: str, settings: ExtractionSettings
) -> bool:
    """아주경제 포토 기사의 빅카인즈 캡션 검증."""
    host = urlsplit(str(seed.original_url or "")).hostname
    listing_summary = _PHOTO_CREDIT.sub("", seed.summary, count=1)
    normalized_summary = normalized_text(listing_summary)
    normalized_body = normalized_text(text)
    return (
        host in AjuNewsBodyPolicy.hosts
        and seed.title.lstrip("\u200b \t\r\n").startswith("[포토]")
        and normalized_text(title) == normalized_text(seed.title)
        and len(normalized_body) >= settings.min_summary_chars
        and bool(normalized_summary)
        and normalized_summary in normalized_body
    )


class AjuNewsBodyPolicy:
    hosts: tuple[str, ...] = ("ajunews.com", "www.ajunews.com")

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
        nodes = tree.xpath(
            "//div[@id='articleBody' and "
            "contains(concat(' ', normalize-space(@class), ' '), ' article_con ')]"
        )
        if len(nodes) != 1:
            return None
        for node in nodes[0].xpath(
            ".//script | .//style | .//template | "
            ".//*[contains(concat(' ', normalize-space(@class), ' '), ' relate_box ')] | "
            ".//*[contains(concat(' ', normalize-space(@class), ' '), ' byline ')] | "
            ".//*[contains(concat(' ', normalize-space(@class), ' '), ' keyword_tag ')] | "
            ".//*[contains(concat(' ', normalize-space(@class), ' '), ' news_like_bad ')] | "
            ".//*[contains(concat(' ', normalize-space(@class), ' '), ' view_bottom_cont ')] | "
            ".//*[contains(concat(' ', normalize-space(@class), ' '), ' recommend_news ')] | "
            ".//ul[contains(concat(' ', normalize-space(@class), ' '), ' related ')] | "
            ".//p[contains(concat(' ', normalize-space(@class), ' '), ' copy ')]"
        ):
            node.drop_tree()
        text = nodes[0].text_content().strip()
        evidence = verify_article(seed, title, text, settings)
        return DomainBody(text=text, evidence=evidence)
