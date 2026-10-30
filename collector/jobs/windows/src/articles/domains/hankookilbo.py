from lxml import html
from scrapling import Selector

from articles.domains.base import DomainBody
from articles.matching import verify_article
from articles.models import ArticleSeed
from config import ExtractionSettings


class HankookIlboBodyPolicy:
    hosts: tuple[str, ...] = ("hankookilbo.com", "www.hankookilbo.com")

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
        bodies = [
            node
            for node in tree.iter("div")
            if node.get("id") == "article-view-content"
            and "article-view" in (node.get("class") or "").split()
        ]
        if len(bodies) != 1:
            return None
        for node in bodies[0].xpath(
            ".//button[contains(concat(' ', normalize-space(@class), ' '), ' img-zoomin ')]"
            " | .//script | .//style | .//template"
        ):
            node.drop_tree()
        text = bodies[0].text_content().strip()
        return DomainBody(text=text, evidence=verify_article(seed, title, text, settings))
