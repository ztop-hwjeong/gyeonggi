from urllib.parse import parse_qs, urlsplit

from lxml import html
from scrapling import Selector

from articles.domains.base import DomainBody
from articles.matching import normalized_text, verify_article
from articles.models import ArticleSeed, Evidence
from config import ExtractionSettings


class SbsBodyPolicy:
    hosts: tuple[str, ...] = ("news.sbs.co.kr",)

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
        nodes = []
        for node in tree.iter():
            if not isinstance(node.tag, str) or node.tag.rsplit("}", maxsplit=1)[-1] != "div":
                continue
            if "main_text" not in (node.get("class") or "").split():
                continue
            if "영문 기사 보기" not in node.text_content():
                nodes.append(node)
        if len(nodes) != 1:
            return None
        for node in nodes[0].xpath(".//script | .//style | .//template"):
            node.drop_tree()
        text = nodes[0].text_content().strip()
        evidence = verify_article(seed, title, text, settings)
        canonical = tree.xpath(
            "//link[contains(concat(' ', normalize-space(@rel), ' '), ' canonical ')]/@href"
        )
        normalized_summary = normalized_text(seed.summary)
        if (
            evidence.reason == "본문 길이 부족"
            and len(canonical) == 1
            and _news_id(canonical[0]) == _news_id(url) == _news_id(str(seed.original_url or ""))
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
                reason="SBS 본문 단문 제목·요약 일치",
            )
        return DomainBody(text=text, evidence=evidence)


def _news_id(url: str) -> str | None:
    return parse_qs(urlsplit(url).query).get("news_id", [None])[0]
