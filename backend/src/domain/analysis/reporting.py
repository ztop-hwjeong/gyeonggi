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
    folder_id: UUID | None = None,
    include_descendants: bool = True,
) -> dict[str, Any]:
    if sum(value is not None for value in (article_ids, target_id, folder_id)) != 1:
        raise AnalysisReportError("기사, 분석 대상, 폴더 중 하나만 선택")
    rows = await registry.report_articles(article_ids, target_id, folder_id, include_descendants)
    if not rows:
        raise AnalysisReportError("출력할 기사 없음")
    if article_ids is not None and set(article_ids) != {row["id"] for row in rows}:
        raise AnalysisReportError("없는 기사 또는 제외된 기사 포함")
    topics = await registry.topics()
    if folder_id is not None:
        selected_tags = await registry.folder_topic_ids(folder_id, include_descendants)
        topics = [topic for topic in topics if topic.id in selected_tags]
    articles: list[dict] = []
    for number, row in enumerate(rows, 1):
        if folder_id is None:
            names = await registry.canonical_topic_names(row["id"])
        else:
            links = await registry.canonical_article_topics(row["id"])
            included_ids = {
                link.topic_id for link in links if link.origin in ("ai", "manual_include")
            }
            names = [topic.name for topic in topics if topic.id in included_ids]
        articles.append(
            {
                "number": number,
                "keywords": ", ".join(names),
                "publisher": row["publisher"] or "",
                "title": row["title"],
                "sentiment": row["sentiment"] or "",
                "reason": row["sentiment_reason"] or "",
            }
        )
    return {
        "analysis_date": analysis_date.isoformat(),
        "issues": [{"title": topic.name, "keywords": topic.name} for topic in topics],
        "articles": articles,
    }
