import json
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from collector_http.client import AccessRestrictedError, UnexpectedResponseError
from collector_http.config import HttpSettings
from pydantic import ValidationError

from flows import bigkinds
from sources.bigkinds.client import BigKindsClient, search_payload
from sources.bigkinds.config import BigKindsSettings
from sources.bigkinds.models import ArticleListing, CollectionSummary, ListCollectionRequest
from sources.bigkinds.normalization import normalize_listing, parse_search_response
from sources.bigkinds.storage import (
    UnexpectedPaginationError,
    finalize_collection,
    store_listings,
    store_response,
)


@pytest.fixture
def request_data() -> ListCollectionRequest:
    return ListCollectionRequest(
        search_key='("폰프리" OR "폰 프리") NOT "프리텔레콤"',
        start_date=date(2026, 6, 1),
        end_date=date(2026, 10, 22),
        page_size=2,
    )


@pytest.fixture
def listing() -> dict:
    return {
        "NEWS_ID": "04100078.20261020170553001",
        "DATE": "20261020",
        "PROVIDER": "언론사",
        "TITLE": "<b>폰프리</b> &amp; 교육",
        "PROVIDER_LINK_PAGE": "https://example.org/news/123",
        "CONTENT": "<font color=red>교육</font> 기사 요약",
    }


@pytest.fixture
def summary(tmp_path: Path, request_data: ListCollectionRequest) -> CollectionSummary:
    return CollectionSummary(
        run_id="test-run",
        status="running",
        started_at=datetime.now(UTC),
        request=request_data,
        impersonate="chrome",
        output_directory=tmp_path,
    )


def test_search_passes_query_unchanged_and_uses_page_number(
    request_data: ListCollectionRequest,
) -> None:
    payload = search_payload(request_data, 2)
    assert payload["searchKey"] == request_data.search_key
    assert payload["startDate"] == "2026-06-01"
    assert payload["endDate"] == "2026-10-22"
    assert payload["startNo"] == 2
    assert payload["resultNumber"] == 2


def test_list_client_does_not_fetch_details(request_data: ListCollectionRequest) -> None:
    http = Mock()
    http.request.return_value.content = b"{}"
    client = BigKindsClient(BigKindsSettings(rate_limit_name="test"), http)
    client.warmup()
    client.search(request_data, 1)
    assert [call.args[1].split(".or.kr")[-1] for call in http.request.call_args_list] == [
        "/v2/news/search.do",
        "/api/news/search.do",
    ]
    headers = http.request.call_args.kwargs["headers"]
    assert "User-Agent" not in headers
    assert "Cookie" not in headers


def test_invalid_period_is_rejected_before_collection() -> None:
    with pytest.raises(ValidationError, match="종료일"):
        ListCollectionRequest(
            search_key="a", start_date=date(2026, 6, 2), end_date=date(2026, 6, 1)
        )


def test_listing_keeps_original_url_and_does_not_claim_full_content(listing: dict) -> None:
    article = normalize_listing(listing)
    assert article.title == "폰프리 & 교육"
    assert article.summary == "교육 기사 요약"
    assert str(article.original_url) == "https://example.org/news/123"
    assert article.content_kind == "listing_excerpt"
    assert article.published_on == date(2026, 10, 20)


def test_missing_original_url_does_not_invent_one(listing: dict) -> None:
    listing.pop("PROVIDER_LINK_PAGE")
    assert normalize_listing(listing).original_url is None


@pytest.mark.parametrize("body", [b"<html>error</html>", b'{"success":false}'])
def test_invalid_response_is_not_treated_as_zero_results(body: bytes) -> None:
    with pytest.raises(UnexpectedResponseError):
        parse_search_response(body)


def test_zero_result_is_valid() -> None:
    result = parse_search_response(b'{"totalCount":0,"resultList":[]}')
    assert result.total_count == 0
    assert result.result_list == []


def test_raw_response_remains_when_normalization_fails(
    summary: CollectionSummary, request_data: ListCollectionRequest
) -> None:
    body = b'{"totalCount":1,"resultList":[{"DATE":"invalid"}]}'
    stored = store_response(summary.output_directory, request_data, 1, body)
    with pytest.raises(KeyError):
        bigkinds.normalize_page.fn(stored, summary)
    assert stored.body_path.read_bytes() == body
    metadata = json.loads(stored.metadata_path.read_text(encoding="utf-8"))
    assert metadata["request"]["searchKey"] == request_data.search_key


def test_duplicate_articles_are_deduplicated_in_handoff(
    summary: CollectionSummary, listing: dict
) -> None:
    first = normalize_listing(listing)
    second = first.model_copy(update={"source_id": "second"})
    pages = [
        store_listings(summary.output_directory, 1, 3, [first, second]),
        store_listings(
            summary.output_directory,
            2,
            3,
            [second, first.model_copy(update={"source_id": "third"})],
        ),
    ]
    result = finalize_collection(summary, pages)
    assert result.status == "completed"
    assert result.retrieved_count == 4
    assert result.unique_count == 3
    assert result.duplicate_count == 1
    lines = (summary.output_directory / "articles.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert ArticleListing.model_validate_json(lines[0]).source_id == first.source_id


def test_page_cap_is_reported_as_partial(summary: CollectionSummary, listing: dict) -> None:
    page = store_listings(summary.output_directory, 1, 5, [normalize_listing(listing)])
    result = finalize_collection(summary, [page])
    assert result.status == "partial"
    assert result.initial_total_count == 5
    assert result.unique_count == 1
    assert result.stop_reason is not None


def test_zero_result_creates_empty_handoff(summary: CollectionSummary) -> None:
    page = store_listings(summary.output_directory, 1, 0, [])
    result = finalize_collection(summary, [page])
    assert result.status == "completed"
    assert result.unique_count == 0
    assert (summary.output_directory / "articles.jsonl").read_bytes() == b""


def test_changing_source_count_is_reported(summary: CollectionSummary, listing: dict) -> None:
    first = normalize_listing(listing)
    second = first.model_copy(update={"source_id": "second"})
    pages = [
        store_listings(summary.output_directory, 1, 1, [first]),
        store_listings(summary.output_directory, 2, 2, [second]),
    ]
    result = finalize_collection(summary, pages)
    assert result.status == "partial"
    assert result.stop_reason == "검색 건수 변동"


def test_repeated_page_is_not_silently_accepted(summary: CollectionSummary, listing: dict) -> None:
    article = normalize_listing(listing)
    pages = [
        store_listings(summary.output_directory, 1, 2, [article]),
        store_listings(summary.output_directory, 2, 2, [article]),
    ]
    with pytest.raises(UnexpectedPaginationError):
        finalize_collection(summary, pages)
    assert not (summary.output_directory / "articles.jsonl").exists()


def test_repeated_page_stops_before_next_request(
    summary: CollectionSummary, listing: dict, request_data: ListCollectionRequest
) -> None:
    body = json.dumps({"totalCount": 5, "resultList": [listing]}).encode()
    stored = store_response(summary.output_directory, request_data, 2, body)
    with pytest.raises(UnexpectedPaginationError, match="새로운 기사 없음"):
        bigkinds.normalize_page.fn(stored, summary, frozenset({listing["NEWS_ID"]}))
    assert stored.body_path.exists()
    assert not (summary.output_directory / "pages").exists()


def test_empty_page_with_positive_count_is_failure(
    summary: CollectionSummary, request_data: ListCollectionRequest
) -> None:
    stored = store_response(
        summary.output_directory, request_data, 1, b'{"totalCount":2,"resultList":[]}'
    )
    with pytest.raises(UnexpectedPaginationError, match="비어 있음"):
        bigkinds.normalize_page.fn(stored, summary)


@pytest.mark.parametrize("active,limit,decay", [(False, 1, 0.1), (True, 2, 0.1), (True, 1, 0)])
def test_unsafe_rate_limit_prevents_requests(
    monkeypatch: pytest.MonkeyPatch, active: bool, limit: int, decay: float
) -> None:
    api = Mock()
    api.read_global_concurrency_limit_by_name.return_value = Mock(
        active=active, limit=limit, slot_decay_per_second=decay
    )
    context = Mock()
    context.__enter__ = Mock(return_value=api)
    context.__exit__ = Mock(return_value=None)
    monkeypatch.setattr(bigkinds, "get_client", Mock(return_value=context))
    limiter = Mock()
    monkeypatch.setattr(bigkinds, "rate_limit", limiter)
    with pytest.raises(RuntimeError, match="요청 속도 제한"):
        bigkinds.acquire_request(BigKindsSettings(rate_limit_name="test"), HttpSettings())
    limiter.assert_not_called()


def test_restrictions_are_not_retried() -> None:
    state = Mock()
    state.result.return_value = AccessRestrictedError("restricted")
    assert bigkinds.retry_transient(Mock(), Mock(), state) is False
