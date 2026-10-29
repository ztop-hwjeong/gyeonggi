from scrapling import Selector

from articles.domains.base import DomainBody
from articles.matching import verify_article
from articles.models import ArticleSeed
from config import ExtractionSettings


class ETodayBodyPolicy:
    hosts: tuple[str, ...] = ("etoday.co.kr", "www.etoday.co.kr")

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
        nodes = page.css('div.articleView[itemprop~="articleBody"]')
        if len(nodes) != 1:
            return None
        text = str(nodes[0].get_all_text(separator="\n", strip=True))
        evidence = verify_article(seed, title, text, settings)
        return DomainBody(text=text, evidence=evidence)
