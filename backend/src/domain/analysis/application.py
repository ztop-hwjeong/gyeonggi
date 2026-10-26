from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from domain.analysis.registry import TopicRegistry
from domain.analysis.registry_models import TopicEvidenceCreate, normalize_label
from domain.article_workflow.repository import ArticleWorkflow


class AnalysisApplyError(ValueError):
    pass


class ArticleProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic_ids: list[str] = Field(max_length=100)
    keywords: list[str] = Field(max_length=20)
    sentiment: Literal["", "긍정", "중립", "부정"]
    quote: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=500)
    review_required: bool


class TopicCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=400)
    quote: str = Field(min_length=1, max_length=500)


class RawProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    article: ArticleProposal
    topic_candidates: list[TopicCandidate] = Field(max_length=20)


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
        article = await self._registry.article_content(run.source, run.source_id, run.content_hash)
        if article is None:
            raise AnalysisApplyError("분석 원본 기사 없음")
        texts = (article["title"], article["body"] or "")
        if proposal.article.quote not in texts[0] and proposal.article.quote not in texts[1]:
            raise AnalysisApplyError("기사 원문 인용 불일치")
        selected = proposal.article.topic_ids
        if len(selected) != len(set(selected)):
            raise AnalysisApplyError("주제 ID 중복")
        catalog_ids = {item["id"] for item in run.catalog_snapshot.get("topics", [])}
        if not set(selected).issubset(catalog_ids):
            raise AnalysisApplyError("분석 당시 주제 목록과 ID 불일치")
        for candidate in proposal.topic_candidates:
            if candidate.quote not in texts[0] and candidate.quote not in texts[1]:
                raise AnalysisApplyError("새 주제 후보의 원문 인용 불일치")
            if "," in candidate.name:
                raise AnalysisApplyError("새 주제 후보명에 쉼표 사용 불가")
        topic_ids = [
            current
            for topic_id in selected
            if (current := await self._registry.resolve_topic_id(topic_id)) is not None
        ]
        candidate_results = []
        archived = set(await self._registry.archived_labels())
        for candidate in proposal.topic_candidates:
            if normalize_label(candidate.name) in archived:
                candidate_results.append({"name": candidate.name, "status": "archived"})
                continue
            result = await self._registry.record(
                TopicEvidenceCreate(
                    name=candidate.name,
                    description=candidate.description,
                    source=run.source,
                    source_id=run.source_id,
                    publisher=article["publisher"],
                    quote=candidate.quote,
                )
            )
            candidate_results.append(result.model_dump(mode="json"))
            if result.topic_id:
                topic_ids.append(result.topic_id)
        links = await self._registry.sync_article_topics(
            run.source, run.source_id, list(dict.fromkeys(topic_ids)), run.content_hash
        )
        applied = {
            "article_id": str(run.article_id),
            "source": run.source,
            "source_id": run.source_id,
            "content_hash": run.content_hash,
            "topic_ids": [
                link.topic_id for link in links if link.origin in ("ai", "manual_include")
            ],
            "keywords": proposal.article.keywords,
            "sentiment": proposal.article.sentiment,
            "reason": proposal.article.reason,
            "evidence_quote": proposal.article.quote,
            "review_required": proposal.article.review_required,
            "candidate_results": candidate_results,
        }
        await self._registry.save_application(run_id, applied)
        await self._workflow.evaluate(run.article_id)
        return applied
