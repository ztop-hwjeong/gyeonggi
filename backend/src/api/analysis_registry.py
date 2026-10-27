from datetime import date
from uuid import UUID

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from domain.analysis.application import AnalysisApplication, AnalysisApplyError
from domain.analysis.registry import (
    TopicRegistry,
    TopicRegistryConflictError,
    TopicRegistryError,
    TopicRegistryNotFoundError,
)
from domain.analysis.registry_models import (
    AnalysisAttemptInfo,
    AnalysisRunInfo,
    ArticleTopicOverride,
    CanonicalArticleTopicLink,
    Topic,
    TopicInfo,
    TopicMerge,
    TopicUpdate,
)
from domain.analysis.reporting import AnalysisReportError, report_data
from domain.article_workflow.repository import WorkflowInvalidMaterial, WorkflowNotFound
from domain.templates.rendering import TemplateRenderer, TemplateRenderError

router = APIRouter(prefix="/analysis", tags=["analysis"], route_class=DishkaRoute)


class ReportRequest(BaseModel):
    analysis_date: date
    article_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=100)
    target_id: UUID | None = None
    folder_id: UUID | None = None
    include_descendants: bool = True

    @model_validator(mode="after")
    def one_selection(self) -> "ReportRequest":
        selections = (self.article_ids, self.target_id, self.folder_id)
        if sum(value is not None for value in selections) != 1:
            raise ValueError("기사, 분석 대상, 폴더 중 하나만 선택")
        if self.article_ids is not None and len(set(self.article_ids)) != len(self.article_ids):
            raise ValueError("기사 중복")
        return self


@router.post("/reports/education-audit-press/render")
async def render_analysis_report(
    body: ReportRequest,
    registry: FromDishka[TopicRegistry],
    renderer: FromDishka[TemplateRenderer],
) -> Response:
    try:
        data = await report_data(
            registry,
            body.analysis_date,
            body.article_ids,
            body.target_id,
            body.folder_id,
            body.include_descendants,
        )
        content = await run_in_threadpool(renderer.render, "education-audit-press", "1.1.0", data)
    except TopicRegistryNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except AnalysisReportError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except TopicRegistryError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except TemplateRenderError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="education-audit-press-report.xlsx"'},
    )


@router.get("/topics")
async def topics(registry: FromDishka[TopicRegistry]) -> list[TopicInfo]:
    return await registry.topics()


@router.post("/topics")
async def create_topics(body: list[Topic], registry: FromDishka[TopicRegistry]) -> list[TopicInfo]:
    try:
        return await registry.ensure_topics(body)
    except TopicRegistryConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except TopicRegistryError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.post("/runs/{run_id}/apply")
async def apply_analysis(run_id: UUID, application: FromDishka[AnalysisApplication]) -> dict:
    try:
        return await application.apply(run_id)
    except TopicRegistryNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except TopicRegistryConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except AnalysisApplyError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except WorkflowInvalidMaterial as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except WorkflowNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except TopicRegistryError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/runs/{run_id}")
async def run(run_id: UUID, registry: FromDishka[TopicRegistry]) -> AnalysisRunInfo:
    try:
        return await registry.run(run_id)
    except TopicRegistryNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/runs/{run_id}/attempts")
async def analysis_attempts(
    run_id: UUID, registry: FromDishka[TopicRegistry]
) -> list[AnalysisAttemptInfo]:
    await registry.run(run_id)
    return await registry.attempts(run_id)


@router.get("/articles/runs")
async def article_analysis_runs(
    registry: FromDishka[TopicRegistry],
    article_id: UUID,
) -> list[AnalysisRunInfo]:
    return await registry.runs_for_canonical(article_id)


@router.put("/topics/{topic_id}")
async def update_topic(
    topic_id: str, body: TopicUpdate, registry: FromDishka[TopicRegistry]
) -> TopicInfo:
    try:
        return await registry.update(topic_id, body)
    except TopicRegistryConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.delete("/topics/{topic_id}", status_code=204)
async def archive_topic(topic_id: str, registry: FromDishka[TopicRegistry]) -> None:
    try:
        await registry.archive(topic_id)
    except TopicRegistryNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/topics/{topic_id}/merge", status_code=204)
async def merge_topic(topic_id: str, body: TopicMerge, registry: FromDishka[TopicRegistry]) -> None:
    try:
        await registry.merge(topic_id, body)
    except TopicRegistryNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except TopicRegistryConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/articles/{article_id}/topics")
async def article_topics(
    article_id: UUID, registry: FromDishka[TopicRegistry]
) -> list[CanonicalArticleTopicLink]:
    return await registry.canonical_article_topics(article_id)


@router.put("/articles/{article_id}/topics/{topic_id}", status_code=204)
async def override_article_topic(
    article_id: UUID,
    topic_id: str,
    body: ArticleTopicOverride,
    registry: FromDishka[TopicRegistry],
) -> None:
    try:
        await registry.override_canonical_article_topic(article_id, topic_id, body)
    except TopicRegistryNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
