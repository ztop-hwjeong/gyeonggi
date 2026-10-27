from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from domain.analysis.registry import TopicRegistry
from domain.analysis.registry_models import normalize_label
from domain.article_workflow.repository import ArticleWorkflow


class AnalysisApplyError(ValueError):
    pass


class RawProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tags: list[str] = Field(max_length=20)
    sentiment: Literal["긍정", "중립", "부정"]
    mixed_sentiment: bool
    sentiment_reason: str = Field(min_length=1, max_length=160)


class AnalysisApplication:
    def __init__(self, registry: TopicRegistry, workflow: ArticleWorkflow) -> None:
        self._registry = registry
        self._workflow = workflow

    async def apply(self, run_id: UUID) -> dict:
        run = await self._registry.run(run_id)
        await self._workflow.require_news(run.article_id)
        if run.status != "completed" or run.model_draft is None:
            raise AnalysisApplyError("완료된 기사 분석만 적용 가능")
        try:
            proposal = RawProposal.model_validate(run.model_draft)
        except ValidationError as error:
            raise AnalysisApplyError("분석 원제안 형식 오류") from error
        names = [normalize_label(name) for name in proposal.tags]
        if len(names) != len(set(names)):
            raise AnalysisApplyError("태그 중복")
        if any(not name.strip() or "," in name or len(name) > 80 for name in proposal.tags):
            raise AnalysisApplyError("태그 이름 형식 오류")
        topic_ids = [
            tag_id
            for name in proposal.tags
            if (tag_id := await self._registry.ensure_ai_tag(name)) is not None
        ]
        links = await self._registry.sync_material_tags(
            run.article_id, list(dict.fromkeys(topic_ids))
        )
        applied = {
            "article_id": str(run.article_id),
            "source": run.source,
            "source_id": run.source_id,
            "content_hash": run.content_hash,
            "tags": [link.topic_id for link in links if link.origin in ("ai", "manual_include")],
            "sentiment": proposal.sentiment,
            "mixed_sentiment": proposal.mixed_sentiment,
            "sentiment_reason": proposal.sentiment_reason,
        }
        await self._registry.save_application(run_id, applied)
        await self._registry.save_ai_sentiment(
            run.article_id,
            run_id,
            proposal.sentiment,
            proposal.mixed_sentiment,
            proposal.sentiment_reason,
        )
        await self._workflow.evaluate(run.article_id)
        return applied
