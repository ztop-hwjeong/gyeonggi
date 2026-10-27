from uuid import UUID

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, HTTPException, Query

from domain.article_workflow.models import (
    DecisionHistory,
    DecisionInfo,
    DecisionWrite,
    EvaluationResult,
    FilterRuleInfo,
    FilterRuleUpdate,
    FilterRuleWrite,
    ReapplyRequest,
    ReapplyResult,
    ReprintInfo,
    SentimentInfo,
    SentimentWrite,
    TargetInfo,
    TargetUpdate,
    TargetWrite,
)
from domain.article_workflow.relations import ArticleRelations
from domain.article_workflow.repository import (
    ArticleWorkflow,
    WorkflowConflict,
    WorkflowError,
    WorkflowInvalidMaterial,
    WorkflowNotFound,
)

router = APIRouter(tags=["article-workflow"], route_class=DishkaRoute)


@router.get("/articles/{article_id}/sentiment")
async def article_sentiment(
    article_id: UUID, relations: FromDishka[ArticleRelations]
) -> SentimentInfo:
    try:
        return await relations.sentiment(article_id)
    except WorkflowError as error:
        raise handle(error) from error


@router.put("/articles/{article_id}/sentiment")
async def override_article_sentiment(
    article_id: UUID, body: SentimentWrite, relations: FromDishka[ArticleRelations]
) -> SentimentInfo:
    try:
        return await relations.override_sentiment(article_id, body)
    except WorkflowError as error:
        raise handle(error) from error


@router.get("/articles/{article_id}/reprints")
async def article_reprints(
    article_id: UUID, relations: FromDishka[ArticleRelations]
) -> list[ReprintInfo]:
    try:
        return await relations.reprints(article_id)
    except WorkflowError as error:
        raise handle(error) from error


def handle(error: WorkflowError) -> HTTPException:
    if isinstance(error, WorkflowNotFound):
        return HTTPException(status_code=404, detail=str(error))
    if isinstance(error, WorkflowInvalidMaterial):
        return HTTPException(status_code=422, detail=str(error))
    if isinstance(error, WorkflowConflict):
        return HTTPException(status_code=409, detail=str(error))
    return HTTPException(status_code=503, detail=str(error))


@router.get("/analysis-targets")
async def targets(workflow: FromDishka[ArticleWorkflow]) -> list[TargetInfo]:
    return await workflow.targets()


@router.post("/analysis-targets", status_code=201)
async def create_target(body: TargetWrite, workflow: FromDishka[ArticleWorkflow]) -> TargetInfo:
    return await workflow.save_target(body)


@router.put("/analysis-targets/{target_id}")
async def update_target(
    target_id: UUID, body: TargetUpdate, workflow: FromDishka[ArticleWorkflow]
) -> TargetInfo:
    try:
        return await workflow.save_target(body, target_id)
    except WorkflowError as error:
        raise handle(error) from error


@router.delete("/analysis-targets/{target_id}", status_code=204)
async def archive_target(
    target_id: UUID, workflow: FromDishka[ArticleWorkflow], version: int = Query(ge=1)
) -> None:
    try:
        await workflow.archive_target(target_id, version)
    except WorkflowError as error:
        raise handle(error) from error


@router.get("/article-filter-rules")
async def filter_rules(workflow: FromDishka[ArticleWorkflow]) -> list[FilterRuleInfo]:
    return await workflow.rules()


@router.post("/article-filter-rules/reapply")
async def reapply_filter_rules(
    body: ReapplyRequest, workflow: FromDishka[ArticleWorkflow]
) -> ReapplyResult:
    try:
        return await workflow.reapply(body)
    except WorkflowError as error:
        raise handle(error) from error


@router.post("/article-filter-rules", status_code=201)
async def create_filter_rule(
    body: FilterRuleWrite, workflow: FromDishka[ArticleWorkflow]
) -> FilterRuleInfo:
    try:
        return await workflow.save_rule(body)
    except WorkflowError as error:
        raise handle(error) from error


@router.put("/article-filter-rules/{rule_id}")
async def update_filter_rule(
    rule_id: UUID, body: FilterRuleUpdate, workflow: FromDishka[ArticleWorkflow]
) -> FilterRuleInfo:
    try:
        return await workflow.save_rule(body, rule_id)
    except WorkflowError as error:
        raise handle(error) from error


@router.get("/article-filter-rules/{rule_id}/versions")
async def filter_rule_versions(rule_id: UUID, workflow: FromDishka[ArticleWorkflow]) -> list[dict]:
    return await workflow.rule_versions(rule_id)


@router.delete("/article-filter-rules/{rule_id}", status_code=204)
async def delete_filter_rule(
    rule_id: UUID, workflow: FromDishka[ArticleWorkflow], version: int = Query(ge=1)
) -> None:
    try:
        await workflow.delete_rule(rule_id, version)
    except WorkflowError as error:
        raise handle(error) from error


@router.get("/articles/{article_id}/inclusion")
async def article_inclusion(
    article_id: UUID, workflow: FromDishka[ArticleWorkflow]
) -> DecisionInfo:
    try:
        return await workflow.inclusion(article_id)
    except WorkflowError as error:
        raise handle(error) from error


@router.put("/articles/{article_id}/inclusion")
async def override_inclusion(
    article_id: UUID, body: DecisionWrite, workflow: FromDishka[ArticleWorkflow]
) -> DecisionInfo:
    try:
        await workflow.override(article_id, body)
        return (await workflow.evaluate(article_id)).inclusion
    except WorkflowError as error:
        raise handle(error) from error


@router.get("/articles/{article_id}/targets")
async def article_targets(
    article_id: UUID, workflow: FromDishka[ArticleWorkflow]
) -> list[DecisionInfo]:
    try:
        return await workflow.target_links(article_id)
    except WorkflowError as error:
        raise handle(error) from error


@router.put("/articles/{article_id}/targets/{target_id}")
async def override_target(
    article_id: UUID,
    target_id: UUID,
    body: DecisionWrite,
    workflow: FromDishka[ArticleWorkflow],
) -> list[DecisionInfo]:
    try:
        await workflow.override(article_id, body, target_id)
        await workflow.evaluate(article_id)
        return await workflow.target_links(article_id)
    except WorkflowError as error:
        raise handle(error) from error


@router.get("/articles/{article_id}/decisions")
async def decision_history(
    article_id: UUID, workflow: FromDishka[ArticleWorkflow]
) -> list[DecisionHistory]:
    try:
        return await workflow.history(article_id)
    except WorkflowError as error:
        raise handle(error) from error


@router.post("/articles/{article_id}/filter-evaluation")
async def evaluate_filters(
    article_id: UUID, workflow: FromDishka[ArticleWorkflow]
) -> EvaluationResult:
    try:
        return await workflow.evaluate(article_id)
    except WorkflowError as error:
        raise handle(error) from error
