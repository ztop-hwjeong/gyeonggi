from datetime import UTC, date, datetime
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest
from collector_http.config import HttpSettings
from pydantic import SecretStr
from test_naver import cursor, dated_page, page

from flows import naver
from sources.naver.client import NaverApiError
from sources.naver.config import NaverCredentials, NaverSettings
from sources.naver.models import Cursor, SearchRequest, SearchSummary


@pytest.mark.parametrize(
    "previous,max_pages,expected_calls,expected_status",
    [
        (None, 3, 1, "completed"),
        (cursor([50]), 1, 1, "partial"),
        (cursor([1, 2]), 3, 2, "completed"),
    ],
)
def test_cursor_advances_only_after_confirmed_coverage(
    monkeypatch,
    previous: Cursor | None,
    max_pages,
    expected_calls,
    expected_status,
):
    repository = MagicMock()
    repository.cursor.return_value = previous
    batches = [page(1, [1, 2]), page(3, [3, 4])]
    fetch = Mock(side_effect=[(batch, uuid4()) for batch, _ in batches])
    store = Mock(side_effect=[(items, 0, 0) for _, items in batches])
    monkeypatch.setattr(naver, "fetch_page", fetch)
    monkeypatch.setattr(naver, "store_page", store)
    result = naver.collect(
        SearchRequest(channel="news", terms=("교육",), page_size=2, max_pages=max_pages),
        uuid4(),
        repository,
        MagicMock(),
        NaverSettings(credentials_block="test", rate_limit_name="test"),
        NaverCredentials(client_id=SecretStr("test"), client_secret=SecretStr("test")),
        HttpSettings(),
    )
    assert fetch.call_count == expected_calls
    assert result.status == expected_status
    assert result.cursor_advanced == (expected_status == "completed")
    stored = repository.finish.call_args.args[1]
    assert stored.status == expected_status


def test_failed_fetch_is_not_retried_and_records_unchanged_cursor(monkeypatch):
    repository = MagicMock()
    repository.cursor.return_value = cursor([1, 2])
    fetch = Mock(side_effect=NaverApiError(429, "429", "3600"))
    monkeypatch.setattr(naver, "fetch_page", fetch)
    with pytest.raises(NaverApiError):
        naver.collect(
            SearchRequest(channel="news", terms=("교육",)),
            uuid4(),
            repository,
            MagicMock(),
            NaverSettings(credentials_block="test", rate_limit_name="test"),
            NaverCredentials(client_id=SecretStr("test"), client_secret=SecretStr("test")),
            HttpSettings(),
        )
    assert fetch.call_count == 1
    summary = repository.finish.call_args.args[1]
    assert summary.status == "failed" and not summary.cursor_advanced
    assert summary.error_code == "429"
    repository.pause_requests.assert_called_once_with(3600)


@pytest.mark.parametrize("boundary_page,expected_status", [(19, "completed"), (None, "partial")])
def test_default_window_scans_twenty_pages_without_skipping_unconfirmed_gap(
    monkeypatch, boundary_page, expected_status
):
    repository = MagicMock()
    repository.cursor.return_value = cursor([900])
    batches = [
        page(1 + index * 2, [900 if index + 1 == boundary_page else index * 2, index * 2 + 1])
        for index in range(20)
    ]
    fetch = Mock(side_effect=[(batch, uuid4()) for batch, _ in batches])
    monkeypatch.setattr(naver, "fetch_page", fetch)
    monkeypatch.setattr(
        naver, "store_page", Mock(side_effect=[(items, 0, 0) for _, items in batches])
    )
    result = naver.collect(
        SearchRequest(channel="news", terms=("교육",), page_size=2),
        uuid4(),
        repository,
        MagicMock(),
        NaverSettings(credentials_block="test", rate_limit_name="test"),
        NaverCredentials(client_id=SecretStr("test"), client_secret=SecretStr("test")),
        HttpSettings(),
    )
    assert [call.args[2] for call in fetch.call_args_list] == list(range(1, 40, 2))
    assert result.status == expected_status
    assert result.cursor_advanced == (expected_status == "completed")


@pytest.mark.parametrize(
    "second_day,expected", [("2026-10-20", "completed"), ("2026-10-21", "partial")]
)
def test_backfill_stops_at_confirmed_date_and_never_updates_incremental_cursor(
    monkeypatch, second_day, expected
):
    repository = MagicMock()
    batches = [
        dated_page(1, ["2026-10-23T00:00:00+09:00", "2026-10-22T00:00:00+09:00"], "news"),
        dated_page(3, [f"{second_day}T00:00:00+09:00", f"{second_day}T00:00:00+09:00"], "news"),
    ]
    monkeypatch.setattr(
        naver, "fetch_page", Mock(side_effect=[(batch, uuid4()) for batch, _ in batches])
    )
    monkeypatch.setattr(
        naver, "store_page", Mock(side_effect=[(items, 0, 0) for _, items in batches])
    )
    result = naver.collect(
        SearchRequest(channel="news", terms=("황현필",), page_size=2, max_pages=2),
        uuid4(),
        repository,
        MagicMock(),
        NaverSettings(credentials_block="test", rate_limit_name="test"),
        NaverCredentials(client_id=SecretStr("test"), client_secret=SecretStr("test")),
        HttpSettings(),
        date(2026, 10, 21),
        date(2026, 10, 28),
    )
    assert result.status == expected
    assert not result.cursor_advanced
    repository.cursor.assert_not_called()
    assert repository.finish.call_args.args[2] is None


def test_backfill_links_only_requested_dates_and_keeps_unknown_dates():
    repository = MagicMock()
    repository.save_items.return_value = (0, 0)
    summary = SearchSummary(
        run_id=uuid4(),
        stream_key="test",
        channel="news",
        query="test",
        started_at=datetime.now(UTC),
    )
    page_data = page(1, [], total=3)[0].model_copy(
        update={
            "display": 3,
            "items": [
                {
                    "title": "새 기사",
                    "link": "https://example.test/1",
                    "description": "요약",
                    "pubDate": "Wed, 28 Oct 2026 10:00:00 +0900",
                },
                {
                    "title": "옛 기사",
                    "link": "https://example.test/2",
                    "description": "요약",
                    "pubDate": "Tue, 20 Oct 2026 10:00:00 +0900",
                },
                {"title": "날짜 없음", "link": "https://example.test/3", "description": "요약"},
            ],
        }
    )
    items, _, _ = naver.store_page.fn(
        repository,
        MagicMock(),
        summary,
        uuid4(),
        page_data,
        date(2026, 10, 21),
        date(2026, 10, 28),
    )
    assert len(items) == 3
    linked = repository.save_items.call_args.args[3]
    assert [item.title for item in linked] == ["새 기사", "날짜 없음"]


def test_blog_backfill_links_only_requested_dates_without_inventing_time():
    repository = MagicMock()
    repository.save_items.return_value = (0, 0)
    summary = SearchSummary(
        run_id=uuid4(),
        stream_key="test",
        channel="blog",
        query="test",
        started_at=datetime.now(UTC),
    )
    page_data = page(1, [], total=3)[0].model_copy(
        update={
            "display": 3,
            "items": [
                {
                    "title": "기간 글",
                    "link": "https://blog.naver.com/example/1",
                    "description": "요약",
                    "postdate": "20261028",
                },
                {
                    "title": "이전 글",
                    "link": "https://blog.naver.com/example/2",
                    "description": "요약",
                    "postdate": "20261020",
                },
                {
                    "title": "날짜 없음",
                    "link": "https://blog.naver.com/example/3",
                    "description": "요약",
                },
            ],
        }
    )
    items, _, _ = naver.store_page.fn(
        repository,
        MagicMock(),
        summary,
        uuid4(),
        page_data,
        date(2026, 10, 21),
        date(2026, 10, 28),
    )
    assert len(items) == 3
    linked = repository.save_items.call_args.args[3]
    assert [item.title for item in linked] == ["기간 글", "날짜 없음"]
    assert linked[0].published_at is None and linked[0].published_on == "2026-10-28"
