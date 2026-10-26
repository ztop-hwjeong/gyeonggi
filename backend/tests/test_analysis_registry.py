import pytest
from pydantic import ValidationError

from domain.analysis.application import LegacyTopicCandidate, RawProposal
from domain.analysis.registry_models import (
    ArticleTopicOverride,
    TopicEvidenceCreate,
    normalize_label,
)


def test_label_normalization_merges_case_and_whitespace_only() -> None:
    assert normalize_label("  AI   디지털  ") == "ai 디지털"


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


def test_new_topic_candidate_needs_evidence_but_no_generated_description() -> None:
    proposal = RawProposal.model_validate({"tags": ["교권"], "sentiment": "중립"})
    assert proposal.model_dump() == {"tags": ["교권"], "sentiment": "중립"}
    legacy = LegacyTopicCandidate.model_validate(
        {"name": "교권", "description": "옛 분석 설명", "quote": "교권 보호"}
    )
    assert legacy.model_dump() == {
        "name": "교권",
        "description": "옛 분석 설명",
        "quote": "교권 보호",
    }
    with pytest.raises(ValidationError):
        RawProposal.model_validate({"tags": ["교권"]})
