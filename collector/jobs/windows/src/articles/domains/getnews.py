from lxml import html
from scrapling import Selector

from articles.domains.base import DomainBody
from articles.matching import verify_article
from articles.models import ArticleSeed
from config import ExtractionSettings


class GetnewsBodyPolicy:
    hosts: tuple[str, ...] = ("getnews.co.kr", "www.getnews.co.kr")

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
            for node in tree.iter("article")
            if node.get("id") == "article-view-content-div"
            and {"article-veiw-body", "view-page"} <= set((node.get("class") or "").split())
        ]
        if len(bodies) != 1:
            return None
        for node in bodies[0].xpath(".//script | .//style | .//template"):
            node.drop_tree()
        text = bodies[0].text_content().strip()
        return DomainBody(text=text, evidence=verify_article(seed, title, text, settings))
