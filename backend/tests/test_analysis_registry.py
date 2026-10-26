import pytest
from pydantic import ValidationError

from domain.analysis.registry_models import (
    ArticleTopicOverride,
    PromotionPolicy,
    TopicEvidenceCreate,
    normalize_label,
)


def test_label_normalization_merges_case_and_whitespace_only() -> None:
    assert normalize_label("  AI   디지털  ") == "ai 디지털"


def test_promotion_policy_requires_multiple_independent_articles() -> None:
    assert PromotionPolicy().minimum_articles == 3
    with pytest.raises(ValidationError):
        PromotionPolicy(minimum_articles=1)


def test_evidence_requires_stable_article_identity_and_quote() -> None:
    with pytest.raises(ValidationError):
        TopicEvidenceCreate(
            name="새 주제",
            description="설명",
            source="naver_news",
            source_id="",
            publisher="언론사",
            quote="근거",
        )


def test_article_override_has_explicit_release_state() -> None:
    assert ArticleTopicOverride(decision="release").decision == "release"
