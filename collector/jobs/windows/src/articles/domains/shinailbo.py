from lxml import html
from scrapling import Selector

from articles.domains.base import DomainBody
from articles.matching import verify_article
from articles.models import ArticleSeed
from config import ExtractionSettings


class ShinailboBodyPolicy:
    hosts: tuple[str, ...] = ("shinailbo.co.kr", "www.shinailbo.co.kr")

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
        required = {"article-veiw-body", "view-page"}
        nodes = [
            node
            for node in tree.iter()
            if isinstance(node.tag, str)
            and node.tag.rsplit("}", maxsplit=1)[-1] == "article"
            and required <= set((node.get("class") or "").split())
        ]
        if len(nodes) != 1:
            return None
        for node in nodes[0].xpath(".//script | .//style | .//template"):
            node.drop_tree()
        text = nodes[0].text_content().strip()
        return DomainBody(text=text, evidence=verify_article(seed, title, text, settings))
