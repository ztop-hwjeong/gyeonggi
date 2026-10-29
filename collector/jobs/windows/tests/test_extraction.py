from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from articles.adaptive import PostgresAdaptiveStorage, ProfileContext
from articles.extraction import ArticleExtractor, ExtractionRejectedError, NoTextBodyError
from articles.matching import verify_article
from articles.models import ArticleSeed
from config import ExtractionSettings


def test_extracts_article_and_trains_verified_publisher_profile(
    seed: ArticleSeed, article_html: bytes, repository: Mock
) -> None:
    result = ArticleExtractor(repository, ExtractionSettings()).extract(
        seed, article_html, str(seed.original_url)
    )
    assert result.evidence.verified
    assert result.method == "trafilatura"
    assert "학교와 지역 도서관" in result.text
    assert "다른 기사와 광고" not in result.text
    saved = repository.save_profile.call_args
    assert saved.args[3]["validation"]["verified"] is True
    assert saved.args[3]["publisher"] == seed.publisher


def test_adaptive_record_is_reused_by_new_extractor(
    seed: ArticleSeed, article_html: bytes, repository: Mock
) -> None:
    ArticleExtractor(repository, ExtractionSettings()).extract(
        seed, article_html, str(seed.original_url)
    )
    changed = article_html.replace(b'id="news-body"', b'id="article-v2" class="updated"')
    result = ArticleExtractor(repository, ExtractionSettings()).extract(
        seed, changed, str(seed.original_url)
    )
    assert result.method == "adaptive"
    assert result.evidence.verified
    assert repository.save_profile.call_count == 2


def test_verified_semantic_body_trains_without_recommended_article_feed(
    seed, article_html, repository
):
    body = article_html.replace(b'id="news-body"', b'itemprop="articleBody"')
    body = body.replace(b"<aside>", b"<aside>" + ("국제 금융 추천 기사 " * 1000).encode())
    extractor = ArticleExtractor(repository, ExtractionSettings())
    first = extractor.extract(seed, body, str(seed.original_url))
    assert first.evidence.verified
    assert first.adaptive_scope
    assert "국제 금융 추천 기사" not in first.text
    replay = extractor.extract(seed, body, str(seed.original_url))
    assert replay.method == "adaptive"
    assert replay.text == first.text


def test_legacy_korean_encoding_keeps_title_body_and_profile(seed, article_html, repository):
    legacy = (
        article_html.decode().replace("<head>", '<head><meta charset="euc-kr">').encode("cp949")
    )
    result = ArticleExtractor(repository, ExtractionSettings()).extract(
        seed, legacy, str(seed.original_url)
    )
    assert result.evidence.verified
    assert "학교와 지역 도서관" in result.text
    repository.save_profile.assert_called()


def test_lossy_decoding_never_trains_profile(seed, article_html, repository):
    damaged = article_html.replace(seed.title.encode(), (seed.title + "\ufffd").encode())
    with pytest.raises(ExtractionRejectedError, match="인코딩"):
        ArticleExtractor(repository, ExtractionSettings()).extract(
            seed, damaged, str(seed.original_url)
        )
    repository.save_profile.assert_not_called()


def test_damaged_advertisement_does_not_block_clean_article(seed, article_html, repository):
    damaged = article_html.replace(b"<aside>", b"<aside>" + "\ufffd".encode())
    result = ArticleExtractor(repository, ExtractionSettings()).extract(
        seed, damaged, str(seed.original_url)
    )
    assert result.evidence.verified
    assert "\ufffd" not in result.text


def test_article_heading_wins_over_generic_publisher_metadata(seed, article_html, repository):
    body = (
        article_html.decode()
        .replace(
            f"<title>{seed.title}</title>",
            '<title>언론사 홈페이지</title><meta property="og:title" content="언론사 홈페이지">',
        )
        .encode()
    )
    result = ArticleExtractor(repository, ExtractionSettings()).extract(
        seed, body, str(seed.original_url)
    )
    assert result.title == seed.title
    assert result.evidence.verified


def test_rendered_utf8_header_overrides_legacy_meta_charset(seed, article_html, repository):
    body = article_html.decode().replace("<head>", '<head><meta charset="euc-kr">').encode()
    result = ArticleExtractor(repository, ExtractionSettings()).extract(
        seed, body, str(seed.original_url), "application/x-rendered-html; charset=utf-8"
    )
    assert result.evidence.verified
    assert "학교와 지역 도서관" in result.text


def test_extracts_json_ld_published_and_modified_datetimes(seed, article_html, repository):
    body = article_html.replace(
        b"</head>",
        (
            b'<script type="application/ld+json">'
            b'{"@type":"NewsArticle","datePublished":"2026-10-23T09:15:00+09:00",'
            b'"dateModified":"2026-10-24T10:20:00+09:00"}'
            b"</script></head>"
        ),
    )
    result = ArticleExtractor(repository, ExtractionSettings()).extract(
        seed, body, str(seed.original_url)
    )
    assert result.original_published_at == datetime(2026, 10, 23, 0, 15, tzinfo=UTC)
    assert result.original_published_on == seed.published_on
    assert result.original_modified_at == datetime(2026, 10, 24, 1, 20, tzinfo=UTC)
    assert result.original_modified_on is not None


def test_extracts_date_only_without_inventing_time(seed, article_html, repository):
    body = article_html.replace(
        b"</head>", b'<meta property="article:published_time" content="2026.10.23."></head>'
    )
    result = ArticleExtractor(repository, ExtractionSettings()).extract(
        seed, body, str(seed.original_url)
    )
    assert result.original_published_on == seed.published_on
    assert result.original_published_at is None


def test_ignores_non_article_json_ld_and_malformed_dates(seed, article_html, repository):
    body = article_html.replace(
        b"</head>",
        (
            b'<script type="application/ld+json">'
            b'{"@type":"BreadcrumbList","datePublished":"2026-99-99"}'
            b"</script>"
            b'<meta property="article:published_time" content="2026-99-99"></head>'
        ),
    )
    result = ArticleExtractor(repository, ExtractionSettings()).extract(
        seed, body, str(seed.original_url)
    )
    assert result.original_published_on is None
    assert result.original_published_at is None


def test_does_not_use_json_ld_creation_date_as_published_at(seed, article_html, repository):
    body = article_html.replace(
        b"</head>",
        (
            b'<script type="application/ld+json">'
            b'{"@type":"NewsArticle","dateCreated":"2026-10-23T09:15:00+09:00"}'
            b"</script></head>"
        ),
    )
    result = ArticleExtractor(repository, ExtractionSettings()).extract(
        seed, body, str(seed.original_url)
    )
    assert result.original_published_on is None
    assert result.original_published_at is None


def test_rejected_page_does_not_overwrite_publisher_record(
    seed: ArticleSeed, article_html: bytes, repository: Mock
) -> None:
    extractor = ArticleExtractor(repository, ExtractionSettings())
    extractor.extract(seed, article_html, str(seed.original_url))
    with pytest.raises(ExtractionRejectedError):
        extractor.extract(
            seed, b"<html><title>Login</title><body>Sign in</body></html>", str(seed.original_url)
        )
    assert repository.save_profile.call_count == 1


def test_publisher_and_hostname_are_separate_profile_scopes(
    seed: ArticleSeed, repository: Mock
) -> None:
    extractor = ArticleExtractor(repository, ExtractionSettings())
    first = extractor.scope_key(seed, "https://example.org/news/1")
    assert first != extractor.scope_key(seed, "https://other.example.org/news/1")
    assert first != extractor.scope_key(
        seed.model_copy(update={"publisher": "다른언론"}), "https://example.org/news/1"
    )


def test_summary_only_is_not_accepted_as_full_article(seed: ArticleSeed) -> None:
    result = verify_article(seed, seed.title, seed.summary, ExtractionSettings(min_body_chars=40))
    assert not result.verified
    assert "목록 요약" in result.reason


def test_matching_handles_whitespace_punctuation_and_partial_excerpt(
    seed: ArticleSeed, article_text: str
) -> None:
    result = verify_article(seed, seed.title, article_text.replace(" ", "\n"), ExtractionSettings())
    assert result.verified
    assert result.snippet_match_fraction == 1


def test_correct_title_with_wrong_body_is_rejected(seed: ArticleSeed) -> None:
    body = "반도체 수출과 국제 금융 시장의 변화에 대한 경제 기사다. " * 30
    result = verify_article(seed, seed.title, body, ExtractionSettings())
    assert not result.verified


@pytest.mark.parametrize("ellipsis", ["...", "…"])
def test_disjoint_search_snippets_are_matched_separately(seed, ellipsis):
    first = (
        "교육청은 지역사회와 함께 학생들의 안전한 귀가를 지원하기 위한 "
        "새로운 협력 사업을 시작한다고 밝혔다."
    )
    last = (
        "학부모 대표들은 학교 현장의 다양한 의견을 충분히 수렴하고 "
        "지원 인력을 확대해야 한다고 강조했다."
    )
    summary = first + ellipsis + last
    body = first + " 학교별 이동 동선과 차량 배정, 사업 예산과 관련한 논의가 이어졌다. " * 12 + last
    edited = seed.model_copy(update={"summary": summary})
    result = verify_article(edited, seed.title, body, ExtractionSettings())
    assert result.verified
    assert result.snippet_match_fraction == 1
    wrong = verify_article(
        edited, seed.title, "국제 금융 시장과 수출 실적을 분석했다. " * 40, ExtractionSettings()
    )
    assert not wrong.verified


def test_short_disjoint_snippets_require_enough_matched_text(seed):
    first = "지역사회와연계한학생귀가지원사업이이번학기부터시작된다"
    last = "학부모대표들은안전한교육환경을위한지원인력확충을요구했다"
    edited = seed.model_copy(update={"summary": first + "…" + last})
    padding = "국제금융시장과반도체수출증가에대한경제동향분석결과를발표했다" * 20
    assert verify_article(edited, seed.title, first + padding + last, ExtractionSettings()).verified
    assert not verify_article(edited, seed.title, first + padding, ExtractionSettings()).verified


def test_edited_article_is_accepted_by_title_and_summary_similarity(seed: ArticleSeed) -> None:
    summary = (
        "새 학기를 앞두고 지역 교육청의 방과후 교실 운영 계획을 둘러싼 논의가 이어지고 있다. "
        "학부모 대표들은 운영 시간 확대와 강사 채용 절차 공개를 요청하면서 "
        "학생들의 안전한 귀가를 위한 대책도 함께 마련해야 한다고 강조했다. "
        "교육청은 다음 주 협의회를 열어 학교별 수요를 확인하고 운영 계획을 확정할 예정이다."
    )
    body = (
        "새 학기를 앞두고 지역 교육청의 방과후 교실 운영 계획을 둘러싼 논의가 이어지고 있다. "
        "학부모 대표들은 운영 시간 확대와 강사 채용 절차 공개를 요청했다. "
        "귀가 안전 대책도 요구했다. 학교별 수요를 확인한 뒤 운영 계획을 "
        "확정하기 위해 교육청은 다음 주 협의회를 개최한다. "
        "학교 담당자와 학부모 대표가 참석하는 이번 협의회에서는 교실 배정과 이동 동선, "
        "귀가 차량 운영에 필요한 예산도 논의한다. 교육청 관계자는 학교 현장의 의견을 "
        "충분히 반영하고 추가 수요가 확인되는 학교에 지원 인력을 배치하겠다고 밝혔다."
    )
    edited_seed = seed.model_copy(update={"summary": summary})
    result = verify_article(edited_seed, seed.title, body, ExtractionSettings())
    assert result.verified
    assert result.snippet_match_fraction < 0.5
    assert result.summary_score is not None and result.summary_score >= 65
    assert "편집 차이 허용" in result.reason

    unrelated_title = verify_article(
        edited_seed, "국제 금융 시장과 수출 실적 분석", body, ExtractionSettings()
    )
    assert not unrelated_title.verified


def test_storage_adapter_rejects_unverified_training(repository: Mock) -> None:
    store = PostgresAdaptiveStorage(
        repository,
        "test",
        ProfileContext("a", "https://example.org", "id", "url"),
        "https://example.org",
    )
    with pytest.raises(ValueError, match="검증"):
        store.save(Mock(), "article-body")
    repository.save_profile.assert_not_called()


def test_registered_domain_policy_is_called_before_training(seed, repository):
    url = "https://news.kbs.co.kr/news/view.do?ncd=1234"
    seeded = seed.model_copy(update={"original_url": url})
    markup = (
        f'<html><title>{seed.title}</title><h1>{seed.title}</h1>'
        '<div id="cont_newstext"></div>'
        '<div id="mailHtmlContents"><div class="view_con_text"></div></div>'
        '<div class="player-app"></div><script>const newsCode: "1234"</script></html>'
    ).encode()
    with pytest.raises(NoTextBodyError, match="영상 제공"):
        ArticleExtractor(repository, ExtractionSettings()).extract(seeded, markup, url)
    repository.save_profile.assert_not_called()


def test_news1_structured_body_is_verified_without_adaptive_training(
    seed, article_text, repository
):
    import json

    payload = {"props": {"pageProps": {"articleView": {
        "id": "1", "title": seed.title,
        "contentArrange": [{"type": "text", "content": line} for line in article_text.splitlines()],
    }}}}
    markup = (
        f"<html><head><title>{seed.title}</title></head><body>"
        f'<h1>{seed.title}</h1><script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(payload, ensure_ascii=False)}</script></body></html>"
    ).encode()
    result = ArticleExtractor(repository, ExtractionSettings()).extract(
        seed.model_copy(update={"original_url": "https://www.news1.kr/local/gyeonggi/1"}),
        markup,
        "https://www.news1.kr/local/gyeonggi/1",
    )
    assert result.method == "domain"
    assert result.text == article_text
    repository.save_profile.assert_not_called()
