from lxml import html
from scrapling import Selector

from articles.domains.base import DomainBody
from articles.matching import verify_article
from articles.models import ArticleSeed
from config import ExtractionSettings


class MkBodyPolicy:
    hosts: tuple[str, ...] = ("mk.co.kr", "www.mk.co.kr")

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
            "//*[self::section or self::div]["
            "contains(concat(' ', normalize-space(@class), ' '), ' sec_body ')]"
            "/div[contains(concat(' ', normalize-space(@class), ' '), ' news_cnt_detail_wrap ') "
            "and @itemprop='articleBody']"
            " | //div[@id='article_body' and "
            "contains(concat(' ', normalize-space(@class), ' '), ' article_body ')]"
        )
        if len(nodes) != 1:
            return None
        body = nodes[0]
        for node in body.xpath(
            ".//script | .//style | .//template | "
            ".//button[contains(concat(' ', normalize-space(@class), ' '), ' btn_zoom ')]"
        ):
            node.drop_tree()
        text = body.text_content().strip()
        return DomainBody(text=text, evidence=verify_article(seed, title, text, settings))
