import re

from lxml import html
from scrapling import Selector

from articles.domains.base import DomainBody
from articles.matching import normalized_text, verify_article
from articles.models import ArticleSeed, Evidence
from config import ExtractionSettings


class IncheonIlboBodyPolicy:
    hosts: tuple[str, ...] = ("incheonilbo.com", "www.incheonilbo.com")

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
        nodes = [
            node
            for node in tree.iter()
            if isinstance(node.tag, str)
            and node.tag.rsplit("}", maxsplit=1)[-1] == "div"
            and {"dis-none", "for-content"} <= set((node.get("class") or "").split())
        ]
        if len(nodes) != 1:
            return None
        for node in nodes[0].xpath(".//script | .//style | .//template"):
            node.drop_tree()
        text = re.sub(r"\s*/[^/\n]+? 기자\s+\S+@\S+\s*$", "", nodes[0].text_content()).strip()
        evidence = verify_article(seed, title, text, settings)
        if evidence.verified:
            return DomainBody(text=text, evidence=evidence)
        normalized_body = normalized_text(text)
        normalized_summary = normalized_text(re.sub(r"^\[[^]]+\]\s*", "", seed.summary))
        allowed_reasons = {"본문 길이 부족", "목록 요약보다 충분한 본문 필요"}
        if (
            len(normalized_body) >= settings.min_summary_chars
            and seed.title.startswith("[포토]")
            and normalized_text(seed.title) == normalized_text(title)
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
                reason="포토 캡션 제목·요약 일치",
            )
        return DomainBody(text=text, evidence=evidence)
