from lxml import html
from scrapling import Selector

from articles.domains.base import DomainBody
from articles.matching import verify_article
from articles.models import ArticleSeed
from config import ExtractionSettings


class AsiaeBodyPolicy:
    hosts: tuple[str, ...] = ("asiae.co.kr", "view.asiae.co.kr")

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
        containers = tree.xpath(
            "//div[contains(concat(' ', normalize-space(@class), ' '), "
            "' article-body__contents ')]"
        )
        if len(containers) != 1:
            return None
        nodes = containers[0].xpath(
            "./div["
            "contains(concat(' ', normalize-space(@class), ' '), ' cont_article ') and "
            "contains(concat(' ', normalize-space(@class), ' '), ' article_view ')]"
        )
        body = nodes[0] if len(nodes) == 1 else containers[0]
        for node in body.xpath(".//script | .//style | .//template"):
            node.drop_tree()
        text = body.text_content().strip()
        return DomainBody(text=text, evidence=verify_article(seed, title, text, settings))
