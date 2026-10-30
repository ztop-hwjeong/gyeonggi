import re
from copy import deepcopy
from urllib.parse import urlsplit

from lxml import html
from scrapling import Selector

from articles.domains.base import DomainBody
from articles.matching import normalized_text, verify_article
from articles.models import ArticleSeed, Evidence
from config import ExtractionSettings


class KihoIlboBodyPolicy:
    hosts: tuple[str, ...] = ("kihoilbo.co.kr", "www.kihoilbo.co.kr")

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
        articles = [node for node in tree.iter() if node.get("id") == "article-view-content-div"]
        if len(articles) != 1:
            return None
        figures = [
            node
            for node in articles[0].xpath(".//figure")
            if {"photo-layout", "image"} <= set((node.get("class") or "").split())
        ]
        captions = [
            node
            for figure in figures
            for node in figure.xpath(".//figcaption")
            if "text-left" in (node.get("class") or "").split()
        ]
        if len(figures) != 1 or len(captions) != 1:
            return None
        article_without_photo = deepcopy(articles[0])
        for node in article_without_photo.xpath(".//figure | .//script | .//style | .//template"):
            node.drop_tree()
        if normalized_text(article_without_photo.text_content()):
            return None
        text = re.sub(r"\s*[가-힣]{2,4} 기자\s+\S+@\S+\s*$", "", captions[0].text_content()).strip()
        evidence = verify_article(seed, title, text, settings)
        if evidence.verified:
            return DomainBody(text=text, evidence=evidence)
        canonical = tree.xpath(
            "//link[contains(concat(' ', normalize-space(@rel), ' '), ' canonical ')]/@href"
        )
        allowed_reasons = {
            "본문 길이 부족",
            "목록 요약보다 충분한 본문 필요",
            "검증할 요약 문장 부족",
        }
        normalized_body = normalized_text(text)
        normalized_summary = normalized_text(seed.summary)
        if (
            len(canonical) == 1
            and _article_key(canonical[0]) == _article_key(url)
            and _article_key(canonical[0]) == _article_key(str(seed.original_url or ""))
            and normalized_text(seed.title) == normalized_text(title)
            and len(normalized_body) >= settings.min_summary_chars
            and normalized_body in normalized_summary
            and set(evidence.reason.split("; ")) <= allowed_reasons
        ):
            evidence = Evidence(
                verified=True,
                title_score=100,
                snippet_scores=[100],
                snippet_match_fraction=1,
                body_chars=len(normalized_body),
                summary_score=100,
                reason="기호일보 사진 캡션 제목·URL·요약 일치",
            )
        return DomainBody(text=text, evidence=evidence)


def _article_key(url: str) -> tuple[str, str, str]:
    parsed = urlsplit(url)
    return parsed.netloc.lower(), parsed.path, parsed.query
