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
        modern = tree.xpath(
            "//div[@id='articleContent']/div["
            "contains(concat(' ', normalize-space(@class), ' '), ' viewContent ')]"
        )
        if len(modern) == 1:
            for node in modern[0].xpath(
                ".//script | .//style | .//section[contains(@class, 'article-summary-box')] | "
                ".//div[contains(concat(' ', normalize-space(@class), ' '), ' modal ')] | "
                ".//*[contains(@class, 'expendImageBtn')] | "
                ".//*[starts-with(@id, 'div-gpt-ad-')] | "
                ".//*[contains(@class, 'showGoogleBtn')] | "
                ".//*[contains(@class, 'articleCopyright')] | "
                ".//*[contains(concat(' ', normalize-space(@class), ' '), ' byline ')]"
            ):
                node.drop_tree()
            text = str(
                Selector(content=html.tostring(modern[0], encoding="unicode")).get_all_text(
                    separator="\n", strip=True
                )
            )
            return DomainBody(text=text, evidence=verify_article(seed, title, text, settings))
        if modern:
            return DomainBody(text="", evidence=verify_article(seed, title, "", settings))
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
