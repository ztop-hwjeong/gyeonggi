from lxml import html
from scrapling import Selector

from articles.domains.base import DomainBody
from articles.matching import verify_article
from articles.models import ArticleSeed
from config import ExtractionSettings


class AsiaTodayBodyPolicy:
    hosts: tuple[str, ...] = ("asiatoday.co.kr", "www.asiatoday.co.kr")

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
            "//div[contains(concat(' ', normalize-space(@class), ' '), ' news_bm ')]"
        )
        if len(nodes) != 1:
            return None
        for node in nodes[0].xpath(".//script | .//style | .//template"):
            node.drop_tree()
        text = nodes[0].text_content().strip()
        evidence = verify_article(seed, title, text, settings)
        return DomainBody(text=text, evidence=evidence)
