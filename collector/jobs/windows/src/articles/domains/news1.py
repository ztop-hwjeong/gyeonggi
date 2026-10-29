import json
from html import unescape
from urllib.parse import urlsplit

from scrapling import Selector

from articles.domains.base import DomainBody
from articles.matching import normalized_text, verify_article
from articles.models import ArticleSeed
from config import ExtractionSettings


class News1BodyPolicy:
    hosts: tuple[str, ...] = ("news1.kr", "www.news1.kr")

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
        nodes = page.css("script#__NEXT_DATA__")
        if not nodes:
            return None
        try:
            payload = json.loads(str(nodes[0].text))
            article = payload["props"]["pageProps"]["articleView"]
            blocks = article["contentArrange"]
        except (KeyError, TypeError, json.JSONDecodeError):
            return None
        if not isinstance(article, dict) or not isinstance(blocks, list):
            return None
        article_id = str(article.get("id", ""))
        path_id = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
        original_path_id = urlsplit(str(seed.original_url)).path.rstrip("/").rsplit("/", 1)[-1]
        article_title = normalized_text(str(article.get("title", "")))
        if (
            article_id != path_id
            or article_id != original_path_id
            or article_title != normalized_text(title)
        ):
            return None
        text_parts = []
        for block in blocks:
            if (
                not isinstance(block, dict)
                or block.get("type") != "text"
                or not block.get("content")
            ):
                continue
            fragment = Selector(content=f"<div>{unescape(str(block['content']))}</div>")
            text_parts.append(str(fragment.css("div")[0].get_all_text(separator="\n", strip=True)))
        text = "\n".join(part for part in text_parts if part)
        if not text:
            return None
        evidence = verify_article(seed, title, text, settings)
        if evidence.verified:
            return DomainBody(text=text, evidence=evidence)
        source_summary = normalized_text(seed.summary)
        source_title = normalized_text(seed.title)
        short_complete_match = bool(
            evidence.reason == "본문 길이 부족"
            and len(source_summary) >= settings.min_summary_chars
            and normalized_text(text) != source_title
            and evidence.title_score == 100
            and evidence.summary_score == 100
            and evidence.snippet_scores
            and all(score == 100 for score in evidence.snippet_scores)
        )
        if not short_complete_match:
            return DomainBody(text=text, evidence=evidence)
        return DomainBody(
            text=text,
            evidence=evidence.model_copy(
                update={"verified": True, "reason": "도메인 JSON 기사 ID·제목·요약 완전 일치(단문)"}
            ),
        )
