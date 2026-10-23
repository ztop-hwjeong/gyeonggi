from unittest.mock import Mock

import pytest

from articles.adaptive import PostgresAdaptiveStorage, ProfileContext
from articles.extraction import ArticleExtractor, ExtractionRejectedError
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
