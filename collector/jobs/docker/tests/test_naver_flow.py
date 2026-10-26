from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest
from collector_http.config import HttpSettings
from pydantic import SecretStr
from test_naver import cursor, page

from flows import naver
from sources.naver.client import NaverApiError
from sources.naver.config import NaverCredentials, NaverSettings
from sources.naver.models import Cursor, SearchRequest


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
