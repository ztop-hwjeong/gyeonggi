from lxml import html
from scrapling import Selector

from articles.domains.base import DomainBody
from articles.matching import normalized_text, verify_article
from articles.models import ArticleSeed
from config import ExtractionSettings


class NewsPimBodyPolicy:
    hosts: tuple[str, ...] = ("newspim.com", "www.newspim.com")

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
        nodes = tree.xpath("//*[@id='news-contents']")
        if len(nodes) != 1:
            return None
        for node in nodes[0].xpath(".//script | .//style | .//template"):
            node.drop_tree()
        text = nodes[0].text_content().strip()
        evidence = verify_article(seed, title, text, settings)
        # 사진·부고 단문은 단일 본문 영역과 목록 전문이 일치할 때만 수용
        if (
            evidence.reason == "본문 길이 부족; 목록 요약보다 충분한 본문 필요"
            and normalized_text(seed.title) == normalized_text(title)
            and normalized_text(seed.summary) in normalized_text(text)
            and (nodes[0].xpath(".//table") or normalized_text(title).startswith("부고"))
        ):
            evidence = evidence.model_copy(
                update={"verified": True, "reason": "뉴스핌 사진·부고 단문 원문·목록 전문 일치"}
            )
        return DomainBody(text=text, evidence=evidence)
