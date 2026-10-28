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
