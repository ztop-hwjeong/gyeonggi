import re
from urllib.parse import urlsplit

from lxml import html
from scrapling import Selector

from articles.domains.base import DomainBody
from articles.matching import normalized_text, verify_article
from articles.models import ArticleSeed, Evidence
from config import ExtractionSettings


class KyeonginBodyPolicy:
    hosts: tuple[str, ...] = ("kyeongin.com", "www.kyeongin.com")

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
        if seed.title.startswith("[인사]"):
            nodes = page.css("#article-body")
            if len(nodes) != 1:
                return None
            paragraphs = nodes[0].css("p:not(.copyright)")
            text = "\n".join(
                value
                for node in paragraphs
                if (value := str(node.get_all_text(strip=True)).strip())
                and not value.startswith("/")
            )
            evidence = verify_article(seed, title, text, settings)
            canonical = page.css('link[rel="canonical"]::attr(href)').getall()
            if (
                len(canonical) == 1
                and _article_key(canonical[0]) == _article_key(url)
                and _article_key(url) == _article_key(str(seed.original_url or ""))
                and urlsplit(url).hostname in self.hosts
                and normalized_text(title) == normalized_text(seed.title)
                and bool(normalized_text(text))
                and normalized_text(text) != normalized_text(title)
                and normalized_text(text) == normalized_text(seed.summary)
                and "\ufffd" not in text
                and "\ufffd" not in title
            ):
                evidence = evidence.model_copy(
                    update={"verified": True, "reason": "인사 단문 제목·URL·원문 전체 요약 일치"}
                )
            return DomainBody(text=text, evidence=evidence)
        if not seed.title.startswith("[포토]"):
            return None
        tree = html.fromstring(markup)
        nodes = tree.xpath(
            "//figcaption[contains(concat(' ', normalize-space(@class), ' '), ' caption ')]"
        )
        if len(nodes) != 1:
            return None
        text = re.sub(
            r"\s*\d{4}\.\d{1,2}\.\d{1,2}\s*/[^/\n]+?기자\s+\S+@\S+\s*$",
            "",
            nodes[0].text_content(),
        ).strip()
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
        if (
            len(canonical) == 1
            and _article_key(canonical[0]) == _article_key(url)
            and _article_key(canonical[0]) == _article_key(str(seed.original_url or ""))
            and normalized_text(seed.title) == normalized_text(title)
            and len(normalized_text(text)) >= settings.min_summary_chars
            and set(evidence.reason.split("; ")) <= allowed_reasons
        ):
            evidence = Evidence(
                verified=True,
                title_score=100,
                snippet_scores=[],
                snippet_match_fraction=0,
                body_chars=len(normalized_text(text)),
                summary_score=None,
                reason="포토 캡션 제목·URL 일치",
            )
        return DomainBody(text=text, evidence=evidence)


def _article_key(url: str) -> tuple[str, str, str]:
    parsed = urlsplit(url)
    return parsed.netloc.lower(), parsed.path, parsed.query
