from datetime import date
from typing import Any
from uuid import UUID

from domain.analysis.registry import TopicRegistry


class AnalysisReportError(ValueError):
    pass


async def report_data(
    registry: TopicRegistry,
    analysis_date: date,
    article_ids: list[UUID] | None = None,
    target_id: UUID | None = None,
) -> dict[str, Any]:
    if (article_ids is None) == (target_id is None):
        raise AnalysisReportError("기사 또는 분석 대상 중 하나만 선택")
    rows = await registry.report_articles(article_ids, target_id)
    if not rows:
        raise AnalysisReportError("출력할 포함 기사 없음")
    if article_ids is not None and set(article_ids) != {row["id"] for row in rows}:
        raise AnalysisReportError("없는 기사 또는 제외된 기사 포함")
    topics = await registry.topics()
    articles: list[dict] = []
    for number, row in enumerate(rows, 1):
        applied = row["applied_result"]
        names = await registry.canonical_topic_names(row["id"])
        articles.append(
            {
                "number": number,
                "keywords": ", ".join(names),
                "publisher": row["publisher"] or "",
                "title": row["title"],
                "sentiment": applied["sentiment"] if applied else "",
                "reason": (
                    applied["reason"] + (" (검토 필요)" if applied["review_required"] else "")
                    if applied
                    else "분석 전"
                ),
            }
        )
    return {
        "analysis_date": analysis_date.isoformat(),
        "issues": [{"title": topic.name, "keywords": topic.name} for topic in topics],
        "articles": articles,
    }
