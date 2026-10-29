from datetime import UTC, date, datetime

from articles.dates import extract_source_dates


def test_empty_response_has_no_source_dates():
    assert extract_source_dates("", None) == (None, None, None, None)


def test_visible_article_clock_corrects_incorrect_utc_metadata():
    markup = (
        '<meta property="article:published_time" content="2026-10-27T15:34:49+0000">'
        '<script type="application/ld+json">{"@type":"NewsArticle",'
        '"dateModified":"2026-10-27T16:10:00+0000"}</script>'
        '<div class="article-date">입력 2026-10-27 15:34 수정 2026-10-27 16:10</div>'
    )
    published_on, published_at, modified_on, modified_at = extract_source_dates(markup, None)
    assert published_on == modified_on == date(2026, 10, 27)
    assert published_at == datetime(2026, 10, 27, 6, 34, tzinfo=UTC)
    assert modified_at == datetime(2026, 10, 27, 7, 10, tzinfo=UTC)


def test_consistent_utc_metadata_keeps_seconds():
    markup = (
        '<meta property="article:published_time" content="2026-10-27T06:34:49Z">'
        '<p class="date-publish">입력 2026-10-27 15:34</p>'
    )
    assert extract_source_dates(markup, None)[1] == datetime(2026, 10, 27, 6, 34, 49, tzinfo=UTC)


def test_unrelated_visible_clock_cannot_replace_article_metadata():
    markup = (
        '<meta property="article:published_time" content="2026-10-27T06:34:49Z">'
        '<p class="date">입력 2026-10-28 11:30</p>'
    )
    assert extract_source_dates(markup, None)[1] == datetime(2026, 10, 27, 6, 34, 49, tzinfo=UTC)


def test_visible_registered_time_supports_korean_period_without_inventing_missing_time():
    assert extract_source_dates('<ul class="date">등록: 2026.10.27 오후 12:31</ul>', None)[1] == (
        datetime(2026, 10, 27, 3, 31, tzinfo=UTC)
    )
    assert extract_source_dates('<p class="date">입력 2026.10.27</p>', None)[1] is None


def test_compact_og_regdate_is_published_timestamp_only_for_explicit_metadata():
    markup = '<meta property="og:regDate" content="20261029070706">'
    assert extract_source_dates(markup, None)[1] == datetime(2026, 10, 28, 22, 7, 6, tzinfo=UTC)
    assert extract_source_dates('<p class="date">20261029070706</p>', None)[1] is None


def test_debug_news_date_requires_matching_visible_approval_minute():
    source = '<meta name="debug-news-date" content="Wed Oct 28 15:59:41 KST 2026">'
    assert extract_source_dates(source, None)[1] is None
    markup = source + '<p class="article-date">승인 2026-10-28 15:59</p>'
    assert extract_source_dates(markup, None)[1] == datetime(2026, 10, 28, 6, 59, 41, tzinfo=UTC)


def test_approval_and_distribution_are_published_but_updated_is_modified_only():
    assert extract_source_dates('<p class="date">배포일 2026-10-27 10:09</p>', None)[1] == datetime(
        2026, 10, 27, 1, 9, tzinfo=UTC
    )
    published_on, published_at, modified_on, modified_at = extract_source_dates(
        '<p class="date">UPDATED. 2026-10-28 15:07 (수)</p>', None
    )
    assert (published_on, published_at) == (None, None)
    assert modified_on == date(2026, 10, 28)
    assert modified_at == datetime(2026, 10, 28, 6, 7, tzinfo=UTC)
