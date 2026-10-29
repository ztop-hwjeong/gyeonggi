from datetime import UTC, date, datetime
from unittest.mock import Mock
from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError

from sources.naver.client import NaverApiError, NaverClient, parse_response
from sources.naver.config import NaverCredentials, NaverSettings
from sources.naver.models import (
    BackfillPagination,
    Channel,
    Cursor,
    Pagination,
    SearchPage,
    SearchRequest,
)
from sources.naver.normalization import normalize_item


def item(number: int, channel: Channel = "news"):
    value = dict(
        title="교육 <b>정책</b> &amp; 소식",
        link=f"https://example.test/news/{number}",
        description="공개 <b>요약</b>",
    )
    if channel == "news":
        value.update(pubDate="Fri, 23 Oct 2026 10:00:00 +0900", originallink=value["link"])
    elif channel == "blog":
        value.update(
            postdate="20261023",
            bloggername="교육 블로그",
            bloggerlink="https://blog.naver.com/education",
        )
    return normalize_item(channel, value)


def page(start, ids, total=100):
    items = [item(number) for number in ids]
    data = SearchPage(
        lastBuildDate="Fri, 23 Oct 2026 10:00:00 +0900",
        total=total,
        start=start,
        display=len(items),
        items=[{} for _ in items],
    )
    return data, items


def cursor(numbers):
    return Cursor(
        head_ids=[item(number).source_id for number in numbers],
        run_id=uuid4(),
        completed_at=datetime.now(UTC),
    )


def test_merged_terms_are_order_independent_and_new_terms_start_a_new_stream():
    a = SearchRequest(channel="news", terms=("편한교복", "벽깨기교육", "편한교복"))
    b = SearchRequest(channel="news", terms=("벽깨기교육", "편한교복"))
    assert a.stream_key == b.stream_key
    assert '"벽깨기교육" | "편한교복"' == a.query
    assert a.stream_key != SearchRequest(channel="news", terms=("편한교복",)).stream_key
    assert a.stream_key != SearchRequest(channel="blog", terms=b.terms).stream_key


@pytest.mark.parametrize("terms", [("",), ('term" | hack',), ("a|b",)])
def test_terms_are_literal_phrases(terms):
    with pytest.raises(ValidationError):
        SearchRequest(channel="news", terms=terms)


def test_retired_channel_is_rejected_before_collection():
    with pytest.raises(ValidationError):
        SearchRequest.model_validate({"channel": "cafearticle", "terms": ["교육"]})


def test_client_uses_hundred_item_default_display_and_offsets():
    request = SearchRequest(channel="news", terms=("교육",))
    http = Mock()
    client = NaverClient(
        http,
        NaverSettings(credentials_block="test", rate_limit_name="test"),
        NaverCredentials(client_id=SecretStr("test"), client_secret=SecretStr("test")),
    )

    client.fetch(request, 1)
    client.fetch(request, 101)

    assert [call.kwargs["params"] for call in http.request_raw.call_args_list] == [
        {
            "query": request.query,
            "display": 100,
            "start": 1,
            "sort": "date",
            "format": "json",
        },
        {
            "query": request.query,
            "display": 100,
            "start": 101,
            "sort": "date",
            "format": "json",
        },
    ]


def test_bootstrap_only_reads_one_page_without_claiming_historical_coverage():
    state = Pagination(SearchRequest(channel="news", terms=("교육",)), None, 1)
    complete, reason = state.accept(*page(1, range(20), 10000))
    assert complete and reason == "최신 첫 페이지로 초기화"
    assert len(state.head_ids) == 20


def test_existing_boundary_requires_overlap_page_and_includes_late_item():
    request = SearchRequest(channel="news", terms=("교육",), page_size=2)
    state = Pagination(request, cursor([2, 3]), 1)
    assert state.accept(*page(1, [1, 2])) == (False, None)
    assert state.accept(*page(3, [9, 3])) == (False, None)
    complete, reason = state.accept(*page(5, [4, 5]))
    assert complete
    assert reason == "이전 커서 및 겹침 구간 확인"
    assert item(9).source_id in state.seen


def test_unseen_boundary_at_page_cap_cannot_advance_cursor():
    request = SearchRequest(channel="news", terms=("교육",), page_size=2, max_pages=2)
    state = Pagination(request, cursor([80, 81]), 1)
    for start, ids in [(1, [1, 2]), (3, [3, 4])]:
        assert state.accept(*page(start, ids)) == (False, None)
    assert state.boundary_page is None


def test_exhausted_results_allow_deleted_boundary():
    state = Pagination(SearchRequest(channel="news", terms=("교육",), page_size=2), cursor([99]), 1)
    assert state.accept(*page(1, [1], 1))[0]


def test_repeated_and_unexpected_empty_pages_are_not_success():
    request = SearchRequest(channel="news", terms=("교육",), page_size=2)
    state = Pagination(request, cursor([90]), 1)
    state.accept(*page(1, [1, 2]))
    assert state.accept(*page(3, [1, 2])) == (False, "동일 페이지 반복")
    assert Pagination(request, cursor([90]), 1).accept(*page(1, [])) == (
        False,
        "검색 건수가 있으나 빈 페이지",
    )


def test_news_uses_original_domain_as_publisher_code_without_requiring_body():
    listing = normalize_item(
        "news",
        {
            "title": "기사",
            "description": "요약",
            "link": "https://n.news.naver.com/mnews/article/021/1234",
            "originallink": "https://www.munhwa.com/article/1",
        },
    )
    assert listing.publisher_code == "munhwa.com"
    assert listing.publisher_domain == "munhwa.com"
    assert listing.publisher is None
    assert item(1, "blog").publisher_code is None


def test_news_and_blog_keep_publication_dates_and_blog_channel_name():
    assert item(1).title == "교육 정책 & 소식"
    blog = item(2, "blog")
    assert blog.published_on == "2026-10-23"
    assert blog.blog_name == "교육 블로그"
    assert str(blog.blog_url) == "https://blog.naver.com/education"
    published = item(3, "news").published_at
    assert published is not None and published.tzinfo is not None


def dated_page(start, values, channel: Channel = "blog"):
    data, _ = page(start, range(start, start + len(values)))
    items = [
        item(start + index, channel).model_copy(
            update={
                "published_on": value if channel == "blog" else None,
                "published_at": datetime.fromisoformat(value)
                if value and channel == "news"
                else None,
            }
        )
        for index, value in enumerate(values)
    ]
    return data, items


@pytest.mark.parametrize("channel", ["news", "blog"])
def test_deleted_cursor_head_uses_strict_date_boundary_after_overlap(channel):
    previous = cursor([99]).model_copy(
        update={
            "oldest_published_at": datetime(2026, 10, 23, tzinfo=UTC),
            "oldest_published_on": date(2026, 10, 23),
        }
    )
    state = Pagination(SearchRequest(channel=channel, terms=("교육",), page_size=2), previous, 1)
    suffix = "T00:00:00+00:00" if channel == "news" else ""
    for start, days in [(1, [24, 23]), (3, [23, 22])]:
        assert state.accept(
            *dated_page(start, [f"2026-10-{day}{suffix}" for day in days], channel)
        ) == (False, None)
    assert state.accept(
        *dated_page(5, [f"2026-10-21{suffix}", f"2026-10-20{suffix}"], channel)
    ) == (
        False,
        None,
    )
    assert state.date_boundary_reached
    assert state.accept(
        *dated_page(7, [f"2026-10-19{suffix}", f"2026-10-18{suffix}"], channel)
    ) == (True, "이전 수집일 및 겹침 기간 확인")
    saved = state.next_cursor(uuid4(), datetime.now(UTC))
    assert saved.oldest_published_on == (date(2026, 10, 23) if channel == "blog" else None)
    assert saved.oldest_published_at == (
        datetime(2026, 10, 23, tzinfo=UTC) if channel == "news" else None
    )


@pytest.mark.parametrize("values", [["2026-10-21", None], ["2026-10-20", "2026-10-21"]])
def test_missing_or_reversed_dates_disable_date_boundary(values):
    previous = cursor([99]).model_copy(update={"oldest_published_on": date(2026, 10, 23)})
    state = Pagination(SearchRequest(channel="blog", terms=("교육",), page_size=2), previous, 1)
    assert state.accept(*dated_page(1, values)) == (False, None)
    assert state.accept(*dated_page(3, ["2026-10-19", "2026-10-18"])) == (False, None)
    assert not state.dates_ordered


def test_date_boundary_is_revoked_if_overlap_page_breaks_date_order():
    previous = cursor([99]).model_copy(update={"oldest_published_on": date(2026, 10, 23)})
    state = Pagination(SearchRequest(channel="blog", terms=("교육",), page_size=2), previous, 1)
    assert state.accept(*dated_page(1, ["2026-10-21", "2026-10-20"])) == (False, None)
    assert state.accept(*dated_page(3, ["2026-10-24", "2026-10-19"])) == (False, None)
    assert state.boundary_page is None
    assert not state.date_boundary_reached


def test_missing_date_after_date_boundary_invalidates_date_evidence_but_keeps_item():
    previous = cursor([99]).model_copy(update={"oldest_published_on": date(2026, 10, 23)})
    state = Pagination(SearchRequest(channel="blog", terms=("교육",), page_size=2), previous, 1)
    state.accept(*dated_page(1, ["2026-10-21", "2026-10-20"]))
    assert state.date_boundary_reached
    assert state.accept(*dated_page(3, [None, "2026-10-19"])) == (False, None)
    assert state.missing_date_count == 1
    assert not state.date_boundary_reached
    assert item(3).source_id in state.seen


@pytest.mark.parametrize("channel,field", [("news", "pubDate"), ("blog", "postdate")])
@pytest.mark.parametrize("missing", [None, "", "absent"])
def test_missing_publication_date_keeps_listing(channel, field, missing):
    data = {"title": "교육", "link": "https://example.com/1", "description": "요약"}
    if missing != "absent":
        data[field] = missing
    result = normalize_item(channel, data)
    assert result.published_at is None and result.published_on is None
    assert result.title == "교육"


def test_cursor_without_dates_does_not_guess_from_collection_time():
    state = Pagination(SearchRequest(channel="blog", terms=("교육",), page_size=2), cursor([99]), 1)
    assert state.accept(*dated_page(1, ["2020-01-02", "2020-01-01"])) == (False, None)


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_api_failure_is_not_empty_results(status):
    response = Mock(
        status_code=status, headers={}, json=Mock(return_value={"error": {"errorCode": "test"}})
    )
    with pytest.raises(NaverApiError) as error:
        parse_response(response, 1)
    assert error.value.code == "test"


def test_response_pagination_mismatch_fails():
    response = Mock(
        status_code=200,
        headers={},
        content=b'{"lastBuildDate":"x","total":3,"start":2,"display":0,"items":[]}',
    )
    with pytest.raises(ValueError, match="시작 위치"):
        parse_response(response, 1)


@pytest.mark.parametrize(
    ("channel", "values"),
    [
        ("news", ["2026-10-23T00:00:00+09:00", "2026-10-21T00:00:00+09:00"]),
        ("blog", ["2026-10-23", "2026-10-21"]),
    ],
)
def test_backfill_confirms_start_boundary_for_news_and_blog(channel, values):
    good = BackfillPagination(date(2026, 10, 21))
    assert good.accept(
        *dated_page(1, values, channel), 2
    ) == (False, None)
    previous = "2026-10-20T00:00:00+09:00" if channel == "news" else "2026-10-20"
    older = "2026-10-19T00:00:00+09:00" if channel == "news" else "2026-10-19"
    assert good.accept(
        *dated_page(3, [previous, older], channel), 2
    ) == (True, "시작일 이전 날짜 경계 확인")


def test_backfill_rejects_missing_or_reversed_dates():
    for values in (
        [None, "2026-10-20T00:00:00+09:00"],
        ["2026-10-20T00:00:00+09:00", "2026-10-23T00:00:00+09:00"],
    ):
        uncertain = BackfillPagination(date(2026, 10, 21))
        assert uncertain.accept(*dated_page(1, values, "news"), 2) == (False, None)
        assert uncertain.accept(
            *dated_page(3, ["2026-10-19T00:00:00+09:00", "2026-10-18T00:00:00+09:00"], "news"), 2
        ) == (False, None)


def test_backfill_repeated_page_and_short_page_remain_incomplete():
    state = BackfillPagination(date(2026, 10, 21))
    first, items = dated_page(1, ["2026-10-23T00:00:00+09:00", "2026-10-22T00:00:00+09:00"], "news")
    assert state.accept(first, items, 2) == (False, None)
    assert state.accept(first.model_copy(update={"start": 3}), items, 2) == (
        False,
        "동일 페이지 반복",
    )
    short = BackfillPagination(date(2026, 10, 21))
    assert short.accept(*dated_page(1, ["2026-10-23T00:00:00+09:00"], "news"), 2) == (
        False,
        "검색 건수보다 짧은 페이지",
    )
