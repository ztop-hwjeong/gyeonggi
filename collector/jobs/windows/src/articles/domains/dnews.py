from urllib.parse import parse_qs, urlsplit

from lxml import html
from scrapling import Selector

from articles.domains.base import DomainBody
from articles.matching import normalized_text, verify_article
from articles.models import ArticleSeed, Evidence
from config import ExtractionSettings


class DnewsBodyPolicy:
    hosts: tuple[str, ...] = ("dnews.co.kr", "www.dnews.co.kr")

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
        articles = [
            node
            for node in tree.iter("div")
            if "newsCont" in (node.get("class") or "").split()
        ]
        if len(articles) != 1:
            return None
        bodies = [
            node
            for node in articles[0].xpath(".//div")
            if "text" in (node.get("class") or "").split()
        ]
        if len(bodies) != 1:
            return None
        for node in bodies[0].xpath(".//script | .//style | .//template"):
            node.drop_tree()
        text = bodies[0].text_content().strip()
        evidence = verify_article(seed, title, text, settings)
        og_urls = tree.xpath("//meta[@property='og:url']/@content")
        normalized_summary = normalized_text(seed.summary)
        if (
            evidence.reason == "본문 길이 부족; 목록 요약보다 충분한 본문 필요"
            and len(og_urls) == 1
            and _article_id(url) == _article_id(str(seed.original_url)) == _article_id(og_urls[0])
            and normalized_text(seed.title) == normalized_text(title)
            and len(normalized_summary) >= settings.min_summary_chars
            and normalized_summary in normalized_text(text)
        ):
            evidence = Evidence(
                verified=True,
                title_score=evidence.title_score,
                snippet_scores=evidence.snippet_scores,
                snippet_match_fraction=evidence.snippet_match_fraction,
                body_chars=evidence.body_chars,
                summary_score=evidence.summary_score,
                reason="대한경제 단문 제목·요약·기사번호 일치",
            )
        return DomainBody(text=text, evidence=evidence)


def _article_id(url: str) -> str | None:
    return parse_qs(urlsplit(url).query).get("idxno", [None])[0]
