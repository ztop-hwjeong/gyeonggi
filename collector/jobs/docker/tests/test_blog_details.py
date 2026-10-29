from datetime import date
from unittest.mock import Mock

import pytest
from prefect.flows import load_flow_from_entrypoint
from pydantic import HttpUrl

from flows.blog_details import blog_seed, terminal_skip_reason
from sources.blogs.extraction import extract_blog, published_datetime
from sources.blogs.http import fetch_blog, validate_public_url
from sources.blogs.models import BlogSeed


def seed(url: str = "https://blog.naver.com/test/123") -> BlogSeed:
    return BlogSeed(
        source="naver_blog",
        source_id="test-123",
        url=HttpUrl(url),
        title="황현필 관련 강연 논란...",
        published_on=date(2026, 10, 28),
    )


def test_prefect_entrypoint_and_storage_row_contract():
    loaded = load_flow_from_entrypoint("src/flows/blog_details.py:collect_pending_blog_details")
    assert loaded.name == "collect-pending-blog-details"
    item = blog_seed(
        {
            "source": "naver_blog",
            "source_id": "123",
            "url": "https://blog.naver.com/test/123",
            "title": "제목",
            "summary": "요약",
            "blog_url": "https://blog.naver.com/test",
            "published_on": "2026-10-21",
        }
    )
    assert str(item.url) == "https://blog.naver.com/test/123"


def test_naver_fetches_matching_postview_and_preserves_both_responses(monkeypatch):
    monkeypatch.setattr("sources.blogs.http.validate_public_url", lambda url: url)
    landing = Mock(
        status_code=200,
        text='<iframe id="mainFrame" src="/PostView.naver?blogId=test&amp;logNo=123">',
        content=b"landing",
        headers={"Content-Type": "text/html"},
    )
    post = Mock(status_code=200, content=b"post", headers={"Content-Type": "text/html"})
    http = Mock()
    http.request_raw.side_effect = [landing, post]
    snapshots = []
    url, body, _ = fetch_blog(http, seed(), lambda stage, url, response: snapshots.append(stage))
    assert "logNo=123" in url
    assert body == b"post"
    assert snapshots == ["html", "postview"]


def test_naver_rejects_different_post_id(monkeypatch):
    monkeypatch.setattr("sources.blogs.http.validate_public_url", lambda url: url)
    landing = Mock(
        status_code=200,
        text='<iframe id="mainFrame" src="/PostView.naver?blogId=test&amp;logNo=999">',
    )
    http = Mock()
    http.request_raw.return_value = landing
    with pytest.raises(ValueError, match="글 ID"):
        fetch_blog(http, seed(), lambda *_: None)
    assert http.request_raw.call_count == 1


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("텍스트 본문 부족", "no_text_body"),
        ("블로그 HTTP 404", "unavailable"),
        ("블로그 HTTP 410", "unavailable"),
        ("블로그 HTTP 403", None),
        ("블로그 HTTP 429", None),
        ("블로그 HTTP 503", None),
    ],
)
def test_only_terminal_cases_are_skipped(message, expected):
    assert terminal_skip_reason(ValueError(message)) == expected


def test_short_blog_body_and_matching_date_are_collected():
    content, evidence = extract_blog(
        '<span class="se-title-text">황현필 관련 강연 논란</span>'
        '<span class="se_publishDate">2026. 10. 28. 10:00</span>'
        '<div class="se-main-container">짧지만 실제로 작성된 블로그 본문입니다.</div>',
        seed(),
    )
    assert content.original_published_on == date(2026, 10, 28)
    assert content.body == "짧지만 실제로 작성된 블로그 본문입니다."
    assert evidence["body_chars"] >= 10


def test_original_published_time_uses_naver_write_epoch_not_relative_label():
    value = published_datetime(
        '<span class="se_publishDate">1시간 전</span>'
        '<script>var postWriteDate = "1793230366123";</script>'
    )
    assert value is not None
    assert value.isoformat() == "2026-10-29T08:32:46.123000+09:00"


def test_original_published_time_uses_published_meta_only():
    value = published_datetime(
        '<meta property="article:modified_time" content="2026-10-29T10:00:00+09:00">'
        '<meta property="article:published_time" content="2026-10-28T15:30:00+09:00">'
    )
    assert value is not None
    assert value.isoformat() == "2026-10-28T15:30:00+09:00"
    assert published_datetime('<span class="se_publishDate">1시간 전</span>') is None


def test_absolute_time_conflicting_with_listed_date_is_rejected():
    with pytest.raises(ValueError, match="목록·원문 작성일 불일치"):
        extract_blog(
            '<span class="se-title-text">황현필 관련 강연 논란</span>'
            '<div class="se-main-container">실제로 작성된 블로그 본문입니다.</div>'
            '<script>var postWriteDate = "1793230366123";</script>',
            seed(),
        )


def test_image_only_and_unrelated_title_are_rejected():
    with pytest.raises(ValueError, match="텍스트 본문 부족"):
        extract_blog(
            '<span class="se-title-text">황현필 관련 강연 논란</span>'
            '<div class="se-main-container"><img src="image.png"></div>',
            seed(),
        )
    with pytest.raises(ValueError, match="목록 제목 불일치"):
        extract_blog(
            '<span class="se-title-text">완전히 다른 주제의 글</span>'
            '<div class="se-main-container">실제로 존재하는 텍스트 본문 내용입니다.</div>',
            seed(),
        )


def test_private_network_target_is_rejected(monkeypatch):
    monkeypatch.setattr(
        "sources.blogs.http.socket.getaddrinfo",
        lambda *_args, **_kwargs: [(None, None, None, None, ("127.0.0.1", 0))],
    )
    with pytest.raises(ValueError, match="공개 IP"):
        validate_public_url("https://localhost/post")
