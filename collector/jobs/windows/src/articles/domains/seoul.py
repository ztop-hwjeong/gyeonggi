from lxml import html
from scrapling import Selector

from articles.domains.base import DomainBody
from articles.matching import verify_article
from articles.models import ArticleSeed
from config import ExtractionSettings


class SeoulBodyPolicy:
    hosts: tuple[str, ...] = ("seoul.co.kr", "www.seoul.co.kr", "go.seoul.co.kr")

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
        content = tree.xpath(
            "//div[contains(concat(' ', normalize-space(@class), ' '), ' content ')]"
        )
        if not content:
            return None
        nodes = content[0].xpath(
            "./div[contains(concat(' ', normalize-space(@class), ' '), ' atic_cnt ')]"
        )
        if len(nodes) == 1:
            for node in nodes[0].xpath(".//script | .//style"):
                node.drop_tree()
            text = nodes[0].text_content().strip()
        else:
            text = ""
        evidence = verify_article(seed, title, text, settings)
        return DomainBody(text=text, evidence=evidence)
