import re
from urllib.parse import urlsplit

from lxml import html
from scrapling import Selector

from articles.domains.base import DomainBody
from articles.matching import normalized_text, verify_article
from articles.models import ArticleSeed, Evidence
from config import ExtractionSettings


class JoongbooBodyPolicy:
    hosts: tuple[str, ...] = ("joongboo.com", "www.joongboo.com")

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
        if not seed.title.startswith("[화보]"):
            return None
        tree = html.fromstring(markup)
        bodies = [
            node
            for node in tree.iter()
            if isinstance(node.tag, str)
            and node.tag.rsplit("}", maxsplit=1)[-1] == "article"
            and {"article-veiw-body", "view-page"} <= set((node.get("class") or "").split())
        ]
        if len(bodies) != 1:
            return None
        captions = []
        for figure in bodies[0].xpath(".//figure"):
            if not {"photo-layout", "image"} <= set((figure.get("class") or "").split()):
                continue
            text = re.sub(r"\s*[가-힣]{2,4}기자\s*$", "", figure.text_content()).strip()
            if len(normalized_text(text)) >= settings.min_summary_chars:
                captions.append(text)
        text = "\n".join(captions)
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
            captions
            and len(canonical) == 1
            and _article_key(canonical[0]) == _article_key(url)
            and _article_key(canonical[0]) == _article_key(str(seed.original_url or ""))
            and normalized_text(seed.title) == normalized_text(title)
            and set(evidence.reason.split("; ")) <= allowed_reasons
        ):
            evidence = Evidence(
                verified=True,
                title_score=100,
                snippet_scores=[],
                snippet_match_fraction=0,
                body_chars=len(normalized_text(text)),
                summary_score=None,
                reason="화보 캡션 제목·URL 일치(요약 대체)",
            )
        return DomainBody(text=text, evidence=evidence)


def _article_key(url: str) -> tuple[str, str, str]:
    parsed = urlsplit(url)
    return parsed.netloc.lower(), parsed.path, parsed.query
