from urllib.parse import urlsplit

from scrapling import Selector

from articles.domains.base import DomainBody
from articles.matching import normalized_text, verify_article
from articles.models import ArticleSeed
from config import ExtractionSettings


class JoongangBodyPolicy:
    hosts: tuple[str, ...] = ("joongang.co.kr", "www.joongang.co.kr")

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
        nodes = page.css("#article_body")
        if len(nodes) != 1:
            return None
        text = str(nodes[0].get_all_text(separator="\n", strip=True))
        evidence = verify_article(seed, title, text, settings)
        canonical = page.css('link[rel="canonical"]::attr(href)').getall()
        original, current = urlsplit(str(seed.original_url or "")), urlsplit(url)
        summary = normalized_text(seed.summary)
        same_article = (
            original.hostname in self.hosts
            and current.hostname in self.hosts
            and original.path.startswith("/article/")
            and original.path == current.path
            and len(canonical) == 1
            and urlsplit(canonical[0]).hostname in self.hosts
            and urlsplit(canonical[0]).path == original.path
        )
        if (
            same_article
            and seed.title.startswith("[인사]")
            and normalized_text(title) == normalized_text(seed.title)
            and bool(summary)
            and summary == normalized_text(text)
            and summary != normalized_text(title)
            and "\ufffd" not in text
            and set(evidence.reason.split("; "))
            <= {"본문 길이 부족", "목록 요약보다 충분한 본문 필요", "검증할 요약 문장 부족"}
        ):
            evidence = evidence.model_copy(
                update={"verified": True, "reason": "인사 단문 제목·URL·원문 전체 요약 일치"}
            )
        if (
            same_article
            and evidence.reason == "제목 불일치"
            and len(summary) >= settings.min_summary_chars
            and summary in normalized_text(text)
        ):
            # 편집된 제목 대신 동일 기사 URL과 목록 요약 전체의 본문 포함 검증
            evidence = evidence.model_copy(
                update={"verified": True, "reason": "동일 기사 URL·요약 전체 일치(제목 편집)"}
            )
        return DomainBody(text=text, evidence=evidence)
