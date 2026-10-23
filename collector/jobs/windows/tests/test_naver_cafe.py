import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, Mock
from uuid import uuid4

import pytest

from articles.models import DetailAttempt, FetchSnapshot
from config import BrowserFetchSettings
from flows import naver_cafe
from sources.naver_cafe import collection
from sources.naver_cafe.browser import capture_article
from sources.naver_cafe.extraction import extract_article
from sources.naver_cafe.models import CafeSettings, CafeTarget


@pytest.fixture
def cafe_seed(seed):
    return seed.model_copy(
        update={
            "source": "naver_cafearticle",
            "published_on": None,
            "original_url": "https://cafe.naver.com/education/123",
        }
    )


@pytest.fixture
def cafe_body(cafe_seed, article_text):
    return {
        "result": {
            "cafeId": 42,
            "articleId": 123,
            "cafe": {"id": 42, "url": "education"},
            "article": {
                "id": 123,
                "subject": cafe_seed.title,
                "isReadable": True,
                "contentHtml": f"<p>{article_text}</p>",
                "writeDate": 1792738814187,
            },
        }
    }


@pytest.mark.parametrize(
    "url",
    [
        "http://cafe.naver.com/a/1",
        "https://cafe.naver.com.evil.test/a/1",
        "https://evil.test/a/1",
        "https://cafe.naver.com:444/a/1",
        "https://user@cafe.naver.com/a/1",
        "https://cafe.naver.com/login",
    ],
)
def test_navigation_rejects_untrusted_or_non_article_urls(url):
    with pytest.raises(ValueError):
        CafeTarget.from_url(url)


def test_target_removes_query_secrets_and_filters_unrelated_responses():
    target = CafeTarget.from_url("https://cafe.naver.com/education/123?art=secret#x")
    assert target.url == "https://cafe.naver.com/education/123"
    assert target.matches_response(
        "https://article.cafe.naver.com/gw/v4/cafes/42/articles/123?requestFrom=A"
    )
    assert not target.matches_response(
        "https://article.cafe.naver.com/gw/v4/cafes/42/articles/123/comments/pages/1"
    )
    assert not target.matches_response("https://article.cafe.naver.com/gw/v4/cafes/42/articles/124")
    numeric = CafeTarget.from_url(
        "https://cafe.naver.com/ArticleRead.nhn?clubid=42&articleid=123&art=secret"
    )
    assert numeric.cafe_id == 42
    assert not numeric.matches_response(
        "https://article.cafe.naver.com/gw/v4/cafes/43/articles/123"
    )


def test_structured_article_preserves_publication_and_checks_identity(cafe_seed, cafe_body):
    result = extract_article(
        json.dumps(cafe_body).encode(), CafeTarget.from_url(str(cafe_seed.original_url)), cafe_seed
    )
    assert result.evidence.verified
    assert result.published_at is not None and result.published_at.tzinfo is UTC
    assert result.method == "naver_cafe_api"


@pytest.mark.parametrize("change", ["article", "cafe", "slug", "unreadable"])
def test_wrong_or_restricted_article_is_never_accepted(cafe_seed, cafe_body, change):
    if change == "article":
        cafe_body["result"]["article"]["id"] = 999
    elif change == "cafe":
        cafe_body["result"]["cafe"]["id"] = 999
    elif change == "slug":
        cafe_body["result"]["cafe"]["url"] = "another"
    else:
        cafe_body["result"]["article"]["isReadable"] = False
    with pytest.raises(ValueError):
        extract_article(
            json.dumps(cafe_body).encode(),
            CafeTarget.from_url(str(cafe_seed.original_url)),
            cafe_seed,
        )


def test_image_only_article_is_preserved_as_rejected_text_extraction(cafe_seed, cafe_body):
    cafe_body["result"]["article"]["contentHtml"] = '<img src="https://example.org/image.jpg">'
    result = extract_article(
        json.dumps(cafe_body).encode(), CafeTarget.from_url(str(cafe_seed.original_url)), cafe_seed
    )
    assert not result.evidence.verified


def test_navigation_captures_page_generated_response_and_reuses_own_tab():
    page = MagicMock()
    page.url = "https://cafe.naver.com/education/122"
    page.evaluate = AsyncMock(return_value="collector-naver-cafe-detail")
    events = []

    async def navigate(*args, **kwargs):
        events.append("navigate")
        return Mock(status=200)

    page.goto = AsyncMock(side_effect=navigate)
    response = Mock()

    async def execute():
        captured = MagicMock()
        value = asyncio.get_running_loop().create_future()
        value.set_result(response)
        captured.value = value
        manager = MagicMock()
        manager.__aenter__ = AsyncMock(return_value=captured)
        manager.__aexit__ = AsyncMock(return_value=False)

        def listen(*args, **kwargs):
            events.append("listen")
            return manager

        page.expect_response.side_effect = listen
        context = Mock(pages=[page], new_page=AsyncMock())
        result = await capture_article(
            context,
            CafeTarget.from_url("https://cafe.naver.com/education/123"),
            BrowserFetchSettings.model_validate({"browser_cdp_url": "http://127.0.0.1:9222"}),
        )
        assert result is response
        context.new_page.assert_not_called()

    asyncio.run(execute())
    assert events == ["listen", "navigate"]
    page.goto.assert_awaited_once_with(
        "https://cafe.naver.com/education/123", wait_until="domcontentloaded", timeout=30000
    )
    page.close.assert_not_called()


def test_browser_response_is_stored_before_restricted_status_is_rejected(monkeypatch, cafe_seed):
    response_id = uuid4()
    repository = Mock()
    repository.save_response.return_value = FetchSnapshot(
        response_id=response_id,
        url="https://article.cafe.naver.com/gw/v4/cafes/42/articles/123",
        status_code=429,
        content_type="application/json",
        sha256="a" * 64,
        received_at=datetime.now(UTC),
        retry_after="1800",
    )
    monkeypatch.setattr(collection, "acquire_navigation", Mock())
    monkeypatch.setattr(
        collection,
        "collect_response",
        AsyncMock(
            return_value=(
                "https://article.cafe.naver.com/gw/v4/cafes/42/articles/123",
                429,
                {"content-type": "application/json", "retry-after": "1800"},
                b'{"error":"rate"}',
            )
        ),
    )
    attempt = collection.collect_article(
        cafe_seed,
        uuid4(),
        repository,
        CafeSettings(),
        BrowserFetchSettings.model_validate({"browser_cdp_url": "http://127.0.0.1:9222"}),
    )
    assert attempt.status == "failed" and attempt.extraction is None
    assert attempt.snapshots[0].response_id == response_id
    assert naver_cafe.pause_seconds(attempt, CafeSettings()) == 1800
    repository.save_attempt.assert_called_once()


def test_batch_stops_after_rate_limit_and_keeps_remaining_items_unprocessed(monkeypatch, cafe_seed):
    repository = Mock()
    queue = MagicMock()
    queue.batch.return_value.__enter__.return_value = [cafe_seed, cafe_seed]
    monkeypatch.setattr(naver_cafe, "CafeQueue", Mock(return_value=queue))
    attempt = DetailAttempt(
        stage="browser_fetch",
        status="failed",
        reason="요청 제한",
        snapshots=[
            FetchSnapshot(
                response_id=uuid4(),
                url="https://article.cafe.naver.com/",
                status_code=429,
                content_type="application/json",
                sha256="a" * 64,
                received_at=datetime.now(UTC),
                retry_after="1800",
            )
        ],
    )
    collect = Mock(return_value=attempt)
    monkeypatch.setattr(naver_cafe, "collect_one", collect)
    monkeypatch.setattr(naver_cafe, "finish_article", naver_cafe.finish_article.fn)
    result = naver_cafe.run_batch(
        repository,
        CafeSettings(),
        BrowserFetchSettings.model_validate({"browser_cdp_url": "http://127.0.0.1:9222"}),
        uuid4(),
    )
    assert collect.call_count == 1
    assert result.status == "partial" and result.requested_count == 2
    queue.pause.assert_called_once_with(1800)


def test_empty_pending_batch_makes_no_browser_request(monkeypatch):
    queue = MagicMock()
    queue.batch.return_value.__enter__.return_value = []
    monkeypatch.setattr(naver_cafe, "CafeQueue", Mock(return_value=queue))
    collect = Mock()
    monkeypatch.setattr(naver_cafe, "collect_one", collect)
    result = naver_cafe.run_batch(
        Mock(),
        CafeSettings(),
        BrowserFetchSettings.model_validate({"browser_cdp_url": "http://127.0.0.1:9222"}),
        uuid4(),
    )
    assert result.status == "completed" and result.requested_count == 0
    collect.assert_not_called()
