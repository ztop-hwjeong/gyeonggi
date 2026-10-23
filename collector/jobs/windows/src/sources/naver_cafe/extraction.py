import json
from datetime import UTC, datetime

from lxml import html
from rapidfuzz.fuzz import ratio

from articles.matching import normalized_text
from articles.models import ArticleSeed, Evidence, ExtractedArticle
from sources.naver_cafe.models import CafeTarget


def extract_article(
    body: bytes, target: CafeTarget, seed: ArticleSeed, title_similarity: float = 70
) -> ExtractedArticle:
    result = json.loads(body)["result"]
    article = result["article"]
    cafe = result["cafe"]
    if int(result["articleId"]) != target.article_id or int(article["id"]) != target.article_id:
        raise ValueError("카페 글 ID 불일치")
    if int(result["cafeId"]) != int(cafe["id"]):
        raise ValueError("카페 응답 내부 ID 불일치")
    if target.cafe_id is not None and int(cafe["id"]) != target.cafe_id:
        raise ValueError("카페 ID 불일치")
    if target.cafe_slug is not None and cafe["url"].casefold() != target.cafe_slug.casefold():
        raise ValueError("카페 주소 불일치")
    if article.get("isReadable") is False or article.get("isBlind") is True:
        raise ValueError("카페 글 열람 제한")
    title = html.fromstring("<div>" + article["subject"] + "</div>").text_content().strip()
    fragment = html.fromstring("<div>" + article["contentHtml"] + "</div>")
    for node in fragment.xpath(".//script|.//style"):
        node.drop_tree()
    text = "\n".join(
        line.strip() for value in fragment.itertext() for line in value.splitlines() if line.strip()
    )
    score = ratio(normalized_text(seed.title), normalized_text(title))
    verified = bool(normalized_text(text)) and score >= title_similarity
    return ExtractedArticle(
        title=title,
        text=text,
        method="naver_cafe_api",
        published_at=datetime.fromtimestamp(article["writeDate"] / 1000, UTC)
        if article.get("writeDate")
        else None,
        evidence=Evidence(
            verified=verified,
            title_score=score,
            snippet_scores=[],
            snippet_match_fraction=0,
            body_chars=len(text),
            reason="카페·글 ID 및 제목 확인" if verified else "본문 없음 또는 제목 불일치",
        ),
    )
