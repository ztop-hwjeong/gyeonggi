import pytest
from pydantic import ValidationError

from domain.analysis.application import RawProposal
from domain.analysis.registry_models import ArticleTopicOverride, normalize_label


def test_label_normalization_merges_case_and_whitespace_only() -> None:
    assert normalize_label("  AI   디지털  ") == "ai 디지털"


def test_article_override_has_explicit_release_state() -> None:
    assert ArticleTopicOverride(decision="release").decision == "release"


def test_analysis_proposal_requires_sentiment_details() -> None:
    proposal = RawProposal.model_validate(
        {
            "tags": ["교권"],
            "sentiment": "중립",
            "mixed_sentiment": False,
            "sentiment_reason": "기사 내용 기준",
        }
    )
    assert proposal.model_dump()["tags"] == ["교권"]
    with pytest.raises(ValidationError):
        RawProposal.model_validate({"tags": ["교권"], "sentiment": "중립"})
