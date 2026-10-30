from lxml import html
from scrapling import Selector

from articles.domains.base import DomainBody
from articles.matching import verify_article
from articles.models import ArticleSeed
from config import ExtractionSettings


class IMAEILBodyPolicy:
    hosts: tuple[str, ...] = ("imaeil.com", "www.imaeil.com")

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
        nodes = [
            node
            for node in tree.iter()
            if isinstance(node.tag, str)
            and node.tag.rsplit("}", maxsplit=1)[-1] == "div"
            and node.get("id") == "articlebody"
        ]
        if len(nodes) != 1:
            return None
        for node in nodes[0].xpath(".//script | .//style | .//template"):
            node.drop_tree()
        text = nodes[0].text_content().strip()
        return DomainBody(text=text, evidence=verify_article(seed, title, text, settings))
