from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.analysis_reports.models import RelevanceRequest, ReportInfo
from domain.analysis_reports.pricing import estimate_request_cost
from domain.analysis_reports.repository import AnalysisReportRepository


@pytest.mark.parametrize(
    ("input_tokens", "expected"),
    [
        (1000, Decimal("0.000612")),
        (272_000, Decimal("0.027712")),
        (272_001, Decimal("0.0551682")),
    ],
)
def test_request_cost_uses_the_per_request_context_tier(input_tokens, expected):
    assert estimate_request_cost(input_tokens) == expected


def test_preview_prices_only_eligible_articles_without_a_batch_context_premium():
    now = datetime.now(UTC)
    report = ReportInfo(
        id=uuid4(),
        target_id=uuid4(),
        target_kind="regular",
        title="보고서",
        description="",
        relevance_criteria="교육청 정책 관련 기사",
        keyword_terms=[],
        keywords_automatic=False,
        is_default=False,
        start_at=None,
        end_at=None,
        version=1,
        created_at=now,
        updated_at=now,
    )
    rows = [
        {
            "article_id": uuid4(),
            "title": "기사",
            "body": "교육청 정책을 다룬 기사 본문",
            "content_hash": "hash",
            "decision": None,
            "ai_status": "unjudged",
            "status": None,
        }
        for _ in range(400)
    ]
    rows += [
        {**rows[0], "decision": "exclude"},
        {**rows[0], "body": ""},
        {**rows[0], "ai_status": "completed", "status": "completed"},
        {**rows[0], "ai_status": "running", "status": "running"},
    ]
    preview, eligible = AnalysisReportRepository._relevance_preview(
        report, rows, RelevanceRequest(scope="filtered")
    )
    assert preview.eligible == len(eligible) == 400
    assert preview.estimated_input_tokens > 272_000
    assert (preview.skipped_excluded, preview.skipped_no_body, preview.skipped_current) == (1, 1, 2)
    expected = (
        Decimal(preview.estimated_input_tokens) * Decimal("0.10")
        + Decimal(preview.estimated_output_tokens) * Decimal("0.50")
    ) / 1_000_000
    assert preview.estimated_cost_usd == float(expected)
    empty, _ = AnalysisReportRepository._relevance_preview(
        report, rows[-4:], RelevanceRequest(scope="filtered")
    )
    assert empty.eligible == 0
    assert empty.estimated_cost_usd == 0
