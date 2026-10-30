from typing import Literal
from uuid import UUID

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query

from domain.analysis_reports.models import (
    RelevanceEnqueue,
    RelevancePreview,
    RelevanceRequest,
    ReportArticleDetail,
    ReportArticlePage,
    ReportBulkDecision,
    ReportCreate,
    ReportDecisionWrite,
    ReportInfo,
    ReportUpdate,
)
from domain.analysis_reports.repository import AnalysisReportRepository

router = APIRouter(prefix="/analysis-reports", tags=["analysis-reports"], route_class=DishkaRoute)


@router.get("")
async def reports(
    repository: FromDishka[AnalysisReportRepository],
    kind: Literal["regular", "current_issue"] | None = None,
    target_id: UUID | None = None,
) -> list[ReportInfo]:
    return await repository.list(kind, target_id)


@router.post("", status_code=201)
async def create_report(
    body: ReportCreate, repository: FromDishka[AnalysisReportRepository]
) -> ReportInfo:
    return await repository.create(body)


@router.get("/{report_id}")
async def report(report_id: UUID, repository: FromDishka[AnalysisReportRepository]) -> ReportInfo:
    return await repository.get(report_id)


@router.put("/{report_id}")
async def update_report(
    report_id: UUID, body: ReportUpdate, repository: FromDishka[AnalysisReportRepository]
) -> ReportInfo:
    return await repository.update(report_id, body)


@router.delete("/{report_id}", status_code=204)
async def delete_report(
    report_id: UUID,
    repository: FromDishka[AnalysisReportRepository],
    version: int = Query(ge=1),
) -> None:
    await repository.delete(report_id, version)


@router.get("/{report_id}/articles")
async def report_articles(
    report_id: UUID,
    repository: FromDishka[AnalysisReportRepository],
    keyword_match: Literal["all", "matched", "unmatched"] = "all",
    inclusion: Literal["all", "unreviewed", "included", "excluded"] = "all",
    q: str | None = Query(default=None, max_length=100),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    ai_relevance: Literal[
        "all", "unjudged", "related", "unrelated", "uncertain", "failed", "pending", "outdated"
    ] = "all",
) -> ReportArticlePage:
    return await repository.articles(
        report_id, keyword_match, inclusion, q, offset, limit, ai_relevance
    )


@router.put("/{report_id}/articles/{article_id}/decision", status_code=204)
async def report_decision(
    report_id: UUID,
    article_id: UUID,
    body: ReportDecisionWrite,
    repository: FromDishka[AnalysisReportRepository],
) -> None:
    await repository.decide(report_id, article_id, body)


@router.put("/{report_id}/decisions", status_code=204)
async def report_bulk_decision(
    report_id: UUID, body: ReportBulkDecision, repository: FromDishka[AnalysisReportRepository]
) -> None:
    await repository.decide_bulk(report_id, body)


@router.post("/{report_id}/relevance/preview")
async def preview_relevance(
    report_id: UUID, body: RelevanceRequest, repository: FromDishka[AnalysisReportRepository]
) -> RelevancePreview:
    return await repository.preview_relevance(report_id, body)


@router.get("/{report_id}/articles/{article_id}")
async def report_article_detail(
    report_id: UUID, article_id: UUID, repository: FromDishka[AnalysisReportRepository]
) -> ReportArticleDetail:
    return await repository.article_detail(report_id, article_id)


@router.post("/{report_id}/relevance/runs", status_code=201)
async def enqueue_relevance(
    report_id: UUID, body: RelevanceRequest, repository: FromDishka[AnalysisReportRepository]
) -> RelevanceEnqueue:
    return await repository.enqueue_relevance(report_id, body)
