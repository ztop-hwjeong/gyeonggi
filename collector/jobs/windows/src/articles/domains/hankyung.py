from lxml import html
from scrapling import Selector

from articles.domains.base import DomainBody
from articles.matching import verify_article
from articles.models import ArticleSeed
from config import ExtractionSettings


class HankyungBodyPolicy:
    hosts: tuple[str, ...] = ("hankyung.com", "www.hankyung.com")

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
        nodes = tree.xpath("//*[@id='articletxt']")
        if len(nodes) != 1:
            return None
        for node in nodes[0].xpath(".//script | .//style | .//template"):
            node.drop_tree()
        text = nodes[0].text_content().strip()
        return DomainBody(text=text, evidence=verify_article(seed, title, text, settings))
