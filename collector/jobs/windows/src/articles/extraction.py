from hashlib import sha256
from typing import cast
from urllib.parse import urlsplit

from lxml.html import HtmlElement
from rapidfuzz.fuzz import ratio
from scrapling import Selector
from trafilatura import bare_extraction
from trafilatura.settings import Document
from w3lib.encoding import html_to_unicode

from articles.adaptive import PostgresAdaptiveStorage, ProfileContext
from articles.dates import extract_source_dates
from articles.matching import normalized_text, verify_article
from articles.models import ArticleSeed, Evidence, ExtractedArticle
from articles.storage import DetailRepository
from config import ExtractionSettings


class ExtractionRejectedError(RuntimeError):
    pass


class ArticleExtractor:
    def __init__(self, repository: DetailRepository, settings: ExtractionSettings) -> None:
        self._repository = repository
        self._settings = settings

    def scope_key(self, seed: ArticleSeed, url: str) -> str:
        host = urlsplit(url).netloc.lower()
        publisher = sha256(seed.publisher.encode()).hexdigest()[:16]
        origin = sha256(host.encode()).hexdigest()[:16]
        return f"{publisher}:{origin}"

    def extract(
        self, seed: ArticleSeed, body: bytes, url: str, content_type: str | None = None
    ) -> ExtractedArticle:
        _, decoded = html_to_unicode(content_type, body)
        scope = self.scope_key(seed, url)
        origin = f"{urlsplit(url).scheme}://{urlsplit(url).netloc}"
        profile = ProfileContext(seed.publisher, origin, seed.source_id, url)
        page = Selector(
            content=decoded,
            url=url,
            adaptive=True,
            storage=PostgresAdaptiveStorage,
            storage_args={
                "repository": self._repository,
                "scope": scope,
                "context": profile,
                "url": origin,
            },
        )
        document = cast(
            Document | None,
            bare_extraction(decoded, url=url, with_metadata=True, include_comments=False),
        )
        original_published_on, original_published_at, original_modified_on, original_modified_at = (
            extract_source_dates(decoded, document.date if document is not None else None)
        )
        title = document.title if document is not None and document.title else ""
        headings = [str(node.get_all_text(strip=True)) for node in page.css("h1")]
        title = max(
            [title, *headings],
            key=lambda value: ratio(normalized_text(seed.title), normalized_text(value)),
        )
        saved = page.retrieve("article-body")
        if saved is not None:
            relocated = page.relocate(
                saved, percentage=self._settings.adaptive_similarity, selector_type=True
            )
            for candidate in relocated:
                if candidate.tag in ("html", "body"):
                    continue
                text = str(candidate.get_all_text(separator="\n", strip=True))
                evidence = verify_article(seed, title, text, self._settings)
                if evidence.verified:
                    self._remember(page, candidate, profile, evidence)
                    return ExtractedArticle(
                        title=title,
                        text=text,
                        method="adaptive",
                        evidence=evidence,
                        adaptive_scope=scope,
                        original_published_on=original_published_on,
                        original_published_at=original_published_at,
                        original_modified_on=original_modified_on,
                        original_modified_at=original_modified_at,
                    )
        candidates = page.css("article,main,section,div,td")[: self._settings.max_dom_candidates]
        text = document.text if document is not None and document.text else ""
        evidence = verify_article(seed, title, text, self._settings)
        if evidence.verified:
            ranked = sorted(
                candidates,
                key=lambda node: ratio(
                    normalized_text(text), normalized_text(str(node.get_all_text(strip=True)))
                ),
                reverse=True,
            )
            for candidate in ranked[:1]:
                candidate_text = str(candidate.get_all_text(separator="\n", strip=True))
                if (
                    ratio(normalized_text(text), normalized_text(candidate_text))
                    >= self._settings.training_similarity
                ):
                    candidate_evidence = verify_article(seed, title, candidate_text, self._settings)
                    if candidate_evidence.verified:
                        self._remember(page, candidate, profile, candidate_evidence)
            return ExtractedArticle(
                title=title,
                text=text,
                method="trafilatura",
                evidence=evidence,
                adaptive_scope=scope if page.retrieve("article-body") else None,
                original_published_on=original_published_on,
                original_published_at=original_published_at,
                original_modified_on=original_modified_on,
                original_modified_at=original_modified_at,
            )
        matching = []
        for candidate in candidates:
            candidate_text = str(candidate.get_all_text(separator="\n", strip=True))
            check = verify_article(seed, title, candidate_text, self._settings)
            if check.verified:
                matching.append((candidate, candidate_text, check))
        if matching:
            # 요약만 있는 짧은 문단과 페이지 전체를 피하는 본문 후보 선택
            candidate, text, evidence = min(matching, key=lambda value: len(value[1]))
            self._remember(page, candidate, profile, evidence)
            return ExtractedArticle(
                title=title,
                text=text,
                method="snippet_dom",
                evidence=evidence,
                adaptive_scope=scope,
                original_published_on=original_published_on,
                original_published_at=original_published_at,
                original_modified_on=original_modified_on,
                original_modified_at=original_modified_at,
            )
        raise ExtractionRejectedError(evidence.reason)

    def _remember(
        self,
        page: Selector,
        element: Selector,
        context: ProfileContext,
        evidence: Evidence,
    ) -> None:
        # Selector도 허용하는 Scrapling 공개 API의 타입 선언 보정
        context.validation = evidence.model_dump(mode="json")
        page.save(cast(HtmlElement, element), "article-body")
