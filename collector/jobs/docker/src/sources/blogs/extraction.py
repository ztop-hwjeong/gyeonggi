import re
from datetime import date
from difflib import SequenceMatcher

from scrapling import Selector

from sources.blogs.models import BlogSeed, ExtractedBlog


def _normalized(value: str) -> str:
    return re.sub(r"\s+", "", re.sub(r"[.]+$", "", value)).lower()


def decode_blog_html(body: bytes, content_type: str) -> str:
    declared = re.search(r"charset\s*=\s*['\"]?([\w-]+)", content_type, re.IGNORECASE)
    if declared is None:
        declared = re.search(rb"charset\s*=\s*['\"]?([\w-]+)", body[:4096], re.IGNORECASE)
    if declared is not None:
        encoding = declared.group(1)
        return body.decode(encoding.decode("ascii") if isinstance(encoding, bytes) else encoding)
    for encoding in ("utf-8", "euc-kr"):
        try:
            return body.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("블로그 HTML 인코딩 판별 실패")


def extract_blog(markup: str, seed: BlogSeed) -> tuple[ExtractedBlog, dict]:
    page = Selector(content=markup, url=str(seed.url))
    title = ""
    for selector in (
        ".se-title-text",
        ".pcol1 .htitle",
        'meta[property="og:title"]',
        "h2",
        "title",
    ):
        if nodes := page.css(selector):
            title = (
                nodes[0].attrib.get("content", "")
                if selector.startswith("meta[")
                else str(nodes[0].get_all_text(strip=True))
            )
            if title:
                break
    body = ""
    body_found = False
    for selector in (
        ".se-main-container",
        "#postViewArea",
        ".tt_article_useless_p_margin",
        ".contents_style",
        "div.article[id^='article_']",
        "#article-view",
        "article",
    ):
        if nodes := page.css(selector):
            body_found = True
            body = str(nodes[0].get_all_text(separator="\n", strip=True))
            if body:
                break
    if not body_found:
        raise ValueError("블로그 본문 구조 없음")
    if len(_normalized(body)) < 10:
        raise ValueError("텍스트 본문 부족")
    listed = _normalized(seed.title)
    actual = _normalized(title)
    score = SequenceMatcher(None, listed, actual).ratio() if listed and actual else 0.0
    if not (listed in actual or actual in listed or score >= 0.55):
        raise ValueError("목록 제목 불일치")
    dates = page.css(".se_publishDate, .blog2_series_date")
    value = str(dates[0].get_all_text(strip=True)) if dates else ""
    match = re.search(r"(20\d{2})\.\s*(\d{1,2})\.\s*(\d{1,2})\.", value)
    published = date(*map(int, match.groups())) if match else None
    if published and seed.published_on and published != seed.published_on:
        raise ValueError("목록·원문 작성일 불일치")
    return (
        ExtractedBlog(title=title, body=body, original_published_on=published),
        {
            "title_score": score,
            "body_chars": len(_normalized(body)),
            "reason": "블로그 제목·본문 구조 확인",
        },
    )
