from copy import deepcopy

from lxml import html
from scrapling import Selector

from articles.domains.base import DomainBody
from articles.matching import verify_article
from articles.models import ArticleSeed
from config import ExtractionSettings


class OhmynewsBodyPolicy:
    hosts: tuple[str, ...] = ("ohmynews.com", "www.ohmynews.com")

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
        nodes = tree.xpath("//*[@itemprop='articleBody' and contains(@class, 'at_contents')]")
        if len(nodes) != 1:
            return None
        body = deepcopy(nodes[0])
        for node in body.xpath(
            ".//script | .//style | .//template | .//noscript | .//iframe | "
            ".//*[@id='dvCenterAd'] | "
            ".//*[contains(concat(' ', normalize-space(@class), ' '), ' arc-btns-wrap ')] | "
            ".//*[contains(@class, 'comment')]"
        ):
            node.drop_tree()
        text = body.text_content().strip()
        evidence = verify_article(seed, title, text, settings)
        return DomainBody(text=text, evidence=evidence)
