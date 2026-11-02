from urllib.parse import urlsplit

from scrapling import Selector

from articles.domains.base import DomainBody
from articles.matching import normalized_text, verify_article
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
        canonical = page.css('link[rel="canonical"]::attr(href)').getall()
        original = urlsplit(str(seed.original_url or ""))
        current = urlsplit(url)
        if (
            seed.title.startswith("[포토]")
            and normalized_text(seed.title) == normalized_text(title)
            and original.hostname in self.hosts
            and current.hostname in self.hosts
            and original.path == current.path
            and len(canonical) == 1
            and urlsplit(canonical[0]).hostname in self.hosts
            and urlsplit(canonical[0]).path == original.path
            and len(normalized_text(text)) >= settings.min_summary_chars
            and set(evidence.reason.split("; "))
            <= {"본문 길이 부족", "목록 요약보다 충분한 본문 필요"}
        ):
            evidence = evidence.model_copy(
                update={"verified": True, "reason": "포토 본문 제목·URL·요약 일치"}
            )
        return DomainBody(text=text, evidence=evidence)
