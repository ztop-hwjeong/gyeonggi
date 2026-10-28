from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from collector_http.config import HttpSettings
from pydantic import HttpUrl
from scrapling import Selector

from articles import pipeline
from articles.domains import get_body_policy
from articles.domains.kbs import KbsBodyPolicy
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
    markup = '<div id="cont_newstext">  </div><script>const video="/news_1234.mp4"</script>'
    if change == "body":
        markup = markup.replace("  </div>", "실제 기사 본문</div>")
    elif change == "video":
        markup = markup.replace("1234.mp4", "1234.jpg")
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
