from lxml import html
from scrapling import Selector

from articles.domains.base import DomainBody
from articles.matching import normalized_text, verify_article
from articles.models import ArticleSeed
from config import ExtractionSettings

_NOTICE_PREFIXES = (
    normalized_text("여러분의 제보가 CBS노컷뉴스의 시작입니다"),
    normalized_text("진실은 노컷, 거짓은 칼컷"),
)


def is_notice_only(text: str) -> bool:
    return normalized_text(text).startswith(_NOTICE_PREFIXES)


class NoCutBodyPolicy:
    hosts: tuple[str, ...] = ("nocutnews.co.kr", "www.nocutnews.co.kr")

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
        nodes = tree.xpath("//div[@id='pnlContent' and @itemprop='articleBody']")
        if len(nodes) != 1:
            return None
        body = nodes[0]
        summaries = tree.xpath(
            "//div[@id='pnlViewBox']/div["
            "contains(concat(' ', normalize-space(@class), ' '), ' summary_l ') "
            "and @data-type='summary']"
        )
        if len(summaries) > 1:
            return None
        for node in body.xpath(".//script | .//style | .//template | .//iframe"):
            node.drop_tree()
        parts = [node.text_content().strip() for node in summaries] + [body.text_content().strip()]
        text = "\n".join(part for part in parts if part)
        return DomainBody(text=text, evidence=verify_article(seed, title, text, settings))
