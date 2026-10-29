import json
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from collector_http.config import HttpSettings
from pydantic import HttpUrl
from scrapling import Selector

from articles import pipeline
from articles.domains import get_body_policy
from articles.domains.kbs import KbsBodyPolicy
from articles.domains.news1 import News1BodyPolicy
from articles.extraction import NoTextBodyError
from articles.models import FetchSnapshot
from config import BrowserFetchSettings, DetailSettings, ExtractionSettings


@pytest.mark.parametrize(
    "change,expected",
    [
        ("none", True),
        ("body", False),
        ("title", False),
        ("video", False),
        ("id", False),
        ("container", False),
        ("original_host", False),
    ],
)
def test_domain_policy_requires_video_identity_and_explicitly_empty_body(seed, change, expected):
    url = "https://news.kbs.co.kr/news/view.do?ncd=1234"
    seeded = seed.model_copy(update={"original_url": HttpUrl(url)})
    markup = (
        '<div id="cont_newstext">  </div>'
        '<div id="mailHtmlContents"><div class="view_con_text"></div></div>'
        '<div class="player-app"></div><script>const newsCode: "1234"</script>'
    )
    if change == "body":
        markup = markup.replace("  </div>", "실제 기사 본문</div>")
    elif change == "video":
        markup = markup.replace('newsCode: "1234"', 'newsCode: "9999"')
    elif change == "container":
        markup = markup.replace("cont_newstext", "other")
    elif change == "id":
        seeded = seeded.model_copy(update={"original_url": HttpUrl(url.replace("1234", "5678"))})
    elif change == "original_host":
        seeded = seeded.model_copy(
            update={"original_url": HttpUrl(url.replace("news.kbs.co.kr", "example.org"))}
        )
    policy = get_body_policy(url)
    assert isinstance(policy, KbsBodyPolicy)
    title = "다른 기사 제목" if change == "title" else seeded.title
    assert policy.has_no_text_body(seeded, Selector(content=markup), title, url, markup) is expected
    assert get_body_policy("https://other.example/article") is None


def news1_markup(article_id, title, blocks):
    payload = {"props": {"pageProps": {"articleView": {
        "id": article_id, "title": title, "contentArrange": blocks,
    }}}}
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'


def test_news1_policy_extracts_only_structured_text_blocks(seed, article_text):
    markup = news1_markup(
        "1",
        seed.title,
        [{"type": "image", "content": "이미지 설명"}]
        + [{"type": "text", "content": line} for line in article_text.splitlines()],
    )
    policy = get_body_policy("https://www.news1.kr/local/gyeonggi/1")
    assert isinstance(policy, News1BodyPolicy)
    result = policy.extract_body(
        seed.model_copy(update={"original_url": "https://www.news1.kr/local/gyeonggi/1"}),
        Selector(content=markup),
        seed.title,
        "https://www.news1.kr/local/gyeonggi/1",
        markup,
        ExtractionSettings(),
    )
    assert result is not None
    assert result.text == article_text


def test_news1_policy_ignores_non_text_or_malformed_blocks(seed, article_text):
    url = "https://www.news1.kr/local/gyeonggi/1"
    body = article_text
    seeded = seed.model_copy(update={"original_url": url, "summary": body})
    markup = news1_markup(
        "1",
        seeded.title,
        ["invalid", {"type": "image", "content": "이미지"}, {"type": "text", "content": body}],
    )
    policy = get_body_policy(url)
    assert isinstance(policy, News1BodyPolicy)
    result = policy.extract_body(
        seeded, Selector(content=markup), seeded.title, url, markup, ExtractionSettings()
    )
    assert result is None or result.text == body


@pytest.mark.parametrize("change", ["url", "id", "title", "summary", "blank", "title_only"])
def test_news1_policy_rejects_unverified_structured_content(seed, change):
    url = "https://www.news1.kr/local/gyeonggi/1"
    body = "경기도교육청은 학교 현장 지원을 강화하고 학부모와 협력해 교육 환경을 개선한다고 밝혔다."
    seeded = seed.model_copy(update={"original_url": url, "summary": body})
    article_id, title, request_url = "1", seeded.title, url
    blocks = [{"type": "text", "content": body}]
    if change == "url":
        request_url = "https://www.news1.kr/local/gyeonggi/2"
    elif change == "id":
        article_id = "2"
    elif change == "title":
        title = "다른 기사 제목"
    elif change == "summary":
        seeded = seeded.model_copy(
            update={"summary": "전혀 다른 내용의 충분히 긴 검색 요약 문장입니다."}
        )
    elif change == "blank":
        blocks = []
    elif change == "title_only":
        blocks = [{"type": "text", "content": seeded.title}]
    markup = news1_markup(article_id, title, blocks)
    policy = get_body_policy(url)
    assert isinstance(policy, News1BodyPolicy)
    result = policy.extract_body(
        seeded,
        Selector(content=markup),
        seeded.title,
        request_url,
        markup,
        ExtractionSettings(),
    )
    if change in {"summary", "title_only"}:
        assert result is not None and not result.evidence.verified
    else:
        assert result is None


def test_kbs_legacy_video_marker_remains_supported(seed):
    url = "https://news.kbs.co.kr/news/view.do?ncd=1234"
    seeded = seed.model_copy(update={"original_url": HttpUrl(url)})
    markup = '<div id="cont_newstext"></div><script>const video="/news_1234.mp4"</script>'
    policy = get_body_policy(url)
    assert isinstance(policy, KbsBodyPolicy)
    assert policy.has_no_text_body(seeded, Selector(content=markup), seeded.title, url, markup)


@pytest.mark.parametrize("stage", ["curl_cffi", "browser_fetch", "browser_rendered"])
def test_only_rendered_body_absence_is_terminal_skip(monkeypatch, seed, repository, stage):
    snapshot = Mock(spec=FetchSnapshot, url=str(seed.original_url), content_type="text/html")
    monkeypatch.setattr(pipeline, "fetch_original", Mock(return_value=snapshot))
    monkeypatch.setattr(pipeline, "fetch_browser", AsyncMock(return_value=snapshot))
    monkeypatch.setattr(pipeline, "fetch_rendered_browser", AsyncMock(return_value=snapshot))
    repository.read_body.return_value = b"html"
    collector = pipeline.ArticleDetailCollector(
        DetailSettings(bigkinds_rate_limit_name="test"),
        HttpSettings(),
        BrowserFetchSettings.model_validate({"browser_cdp_url": "http://127.0.0.1:9222"}),
        ExtractionSettings(),
        repository,
    )
    monkeypatch.setattr(
        collector._extractor,
        "extract",
        Mock(side_effect=NoTextBodyError("영상 제공·텍스트 본문 없음")),
    )
    result = collector.attempt(stage, seed, uuid4())
    assert result.status == ("skipped" if stage == "browser_rendered" else "rejected")
    assert result.skip_reason == ("no_text_body" if stage == "browser_rendered" else None)
