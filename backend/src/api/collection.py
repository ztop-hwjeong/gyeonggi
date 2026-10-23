from typing import Annotated
from uuid import UUID

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Header, Query

from domain.collection.models import (
    SOURCES,
    ArticleIdentity,
    ArticleQuery,
    Overview,
    Pagination,
    PreviewCreate,
    RequestInfo,
    RequestPage,
    RequestQuery,
    RequestReview,
    ResultPage,
    RuleDefinition,
    RuleInfo,
    RulePage,
    RuleQuery,
    RuleUpdate,
    RuleVersion,
    RunCreate,
    SourceInfo,
    StoredArticleDetail,
    StoredArticlePage,
)
from domain.collection.reporting import CollectionReporting
from domain.collection.repository import CollectionRepository

router = APIRouter(tags=["collection"], route_class=DishkaRoute)


@router.get("/overview")
async def overview(reporting: FromDishka[CollectionReporting]) -> Overview:
    return await reporting.overview()


@router.get("/articles")
async def articles(
    reporting: FromDishka[CollectionReporting], query: Annotated[ArticleQuery, Query()]
) -> StoredArticlePage:
    return await reporting.articles(query)


@router.get("/articles/detail")
async def article(
    reporting: FromDishka[CollectionReporting], identity: Annotated[ArticleIdentity, Query()]
) -> StoredArticleDetail:
    return await reporting.article(identity)


@router.get("/sources")
async def sources() -> tuple[SourceInfo, ...]:
    return SOURCES


@router.get("/keyword-rules")
async def rules(
    repository: FromDishka[CollectionRepository], page: Annotated[RuleQuery, Query()]
) -> RulePage:
    return await repository.rules(page)


@router.post("/keyword-rules", status_code=201)
async def create_rule(
    body: RuleDefinition, repository: FromDishka[CollectionRepository]
) -> RuleInfo:
    return await repository.save_rule(body)


@router.get("/keyword-rules/{rule_id}")
async def rule(rule_id: UUID, repository: FromDishka[CollectionRepository]) -> RuleInfo:
    return await repository.rule(rule_id)


@router.put("/keyword-rules/{rule_id}")
async def update_rule(
    rule_id: UUID, body: RuleUpdate, repository: FromDishka[CollectionRepository]
) -> RuleInfo:
    return await repository.save_rule(body, rule_id)


@router.get("/keyword-rules/{rule_id}/versions")
async def versions(
    rule_id: UUID, repository: FromDishka[CollectionRepository]
) -> list[RuleVersion]:
    return await repository.versions(rule_id)


@router.post("/collection-previews", status_code=202)
async def preview(
    body: PreviewCreate,
    repository: FromDishka[CollectionRepository],
    idempotency_key: Annotated[UUID, Header()],
) -> RequestInfo:
    return await repository.enqueue(idempotency_key, body)


@router.post("/collection-runs", status_code=202)
async def run(
    body: RunCreate,
    repository: FromDishka[CollectionRepository],
    idempotency_key: Annotated[UUID, Header()],
) -> RequestInfo:
    return await repository.enqueue(idempotency_key, body)


@router.get("/collection-runs")
async def runs(
    repository: FromDishka[CollectionRepository], query: Annotated[RequestQuery, Query()]
) -> RequestPage:
    return await repository.requests(query)


@router.get("/collection-runs/{request_id}")
async def request(request_id: UUID, repository: FromDishka[CollectionRepository]) -> RequestInfo:
    return await repository.request(request_id)


@router.post("/collection-runs/{request_id}/cancel", status_code=202)
async def cancel(request_id: UUID, repository: FromDishka[CollectionRepository]) -> RequestInfo:
    return await repository.cancel(request_id)


@router.post("/collection-runs/{request_id}/review")
async def review(
    request_id: UUID, body: RequestReview, repository: FromDishka[CollectionRepository]
) -> RequestInfo:
    return await repository.review(request_id, body)


@router.get("/collection-runs/{request_id}/items")
async def results(
    request_id: UUID,
    repository: FromDishka[CollectionRepository],
    page: Annotated[Pagination, Query()],
) -> ResultPage:
    return await repository.results(request_id, page)
