import json
from datetime import date
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest

from control.models import ControlSettings, ManagedRequest
from flows import collection


@pytest.fixture
def request_data():
    return ManagedRequest.model_validate(
        {
            "id": str(uuid4()),
            "source": "bigkinds",
            "mode": "backfill",
            "status": "running",
            "definition": {
                "name": "정책",
                "terms": ["학교 정책"],
                "sources": ["bigkinds"],
                "enabled": False,
            },
            "start_date": "2026-06-01",
            "end_date": "2026-06-02",
        }
    )


def response(total, ids):
    return json.dumps(
        {
            "totalCount": total,
            "resultList": [
                {
                    "NEWS_ID": value,
                    "DATE": "20260601",
                    "PROVIDER": "테스트언론",
                    "TITLE": "학교 정책",
                    "CONTENT": "검색 요약",
                    "PROVIDER_LINK_PAGE": "https://example.org/" + value,
                }
                for value in ids
            ],
        }
    ).encode()


@pytest.mark.parametrize(
    "mode,total,status,calls",
    [
        ("preview", 25, "completed", 1),
        ("backfill", 25, "partial", 2),
        ("backfill", 1, "completed", 2),
    ],
)
def test_preview_and_daily_backfill_limits(monkeypatch, request_data, mode, total, status, calls):
    monkeypatch.setenv("BIGKINDS_RATE_LIMIT_NAME", "test")
    monkeypatch.setattr(collection, "ChromiumHttpClient", MagicMock())
    client = Mock()
    client.search.side_effect = [response(total, ["a"]), response(total, ["b"])]
    monkeypatch.setattr(collection, "BigKindsClient", Mock(return_value=client))
    repository = Mock()
    actual, summary = collection.collect_bigkinds(
        request_data.model_copy(update={"mode": mode}),
        repository,
        Mock(),
        ControlSettings(bigkinds_max_pages_per_day=1),
    )
    assert actual == status
    assert client.search.call_count == calls
    assert summary["retrieved_count"] == calls
    repository.save_response.assert_called()
    if mode == "backfill":
        dates = [call.args[0].start_date for call in client.search.call_args_list]
        assert dates == [date(2026, 6, 1), date(2026, 6, 2)]
        assert all(day["complete"] == (status == "completed") for day in summary["days"])


def test_repeated_page_stops_and_retains_partial_items(monkeypatch, request_data):
    monkeypatch.setenv("BIGKINDS_RATE_LIMIT_NAME", "test")
    monkeypatch.setattr(collection, "ChromiumHttpClient", MagicMock())
    client = Mock()
    client.search.return_value = response(100, ["a"])
    monkeypatch.setattr(collection, "BigKindsClient", Mock(return_value=client))
    request = request_data.model_copy(update={"end_date": request_data.start_date})
    status, summary = collection.collect_bigkinds(request, Mock(), Mock(), ControlSettings())
    assert status == "partial"
    assert client.search.call_count == 1
    assert summary["retrieved_count"] == 1


def test_managed_start_does_not_restart_terminal_request(monkeypatch):
    from flows import managed

    repository = Mock()
    repository.start.return_value = None
    monkeypatch.setattr(managed, "control_repository", lambda: repository)
    monkeypatch.setattr(managed.FlowRunContext, "get", lambda: Mock(flow_run=Mock(id=uuid4())))
    managed.managed_collection.fn(uuid4())
    repository.finish.assert_not_called()
