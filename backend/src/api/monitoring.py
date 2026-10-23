from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query

from domain.monitoring.models import (
    ArticlePage,
    CollectionMetrics,
    ErrorPage,
    ErrorQuery,
    RunInfo,
    RunPage,
    RunQuery,
    Window,
    WorkerSnapshot,
)
from domain.monitoring.prefect import PrefectMonitor
from domain.monitoring.repository import MonitoringRepository

router = APIRouter(
    prefix="/monitoring",
    tags=["monitoring"],
    route_class=DishkaRoute,
    responses={503: {"description": "모니터링 저장소 또는 Prefect 조회 불가"}},
)


@router.get("/metrics")
async def metrics(
    repository: FromDishka[MonitoringRepository],
    window: Annotated[Window, Query()],
) -> CollectionMetrics:
    return await repository.metrics(window)


@router.get("/runs")
async def runs(
    monitor: FromDishka[PrefectMonitor],
    repository: FromDishka[MonitoringRepository],
    query: Annotated[RunQuery, Query()],
) -> RunPage:
    items, total = await monitor.runs(query)
    progress = await repository.progress([run.id for run in items])
    for run in items:
        run.collection = progress.get(run.id)
    return RunPage(items=items, total=total, limit=query.limit, offset=query.offset)


@router.get("/runs/{run_id}", responses={404: {"description": "수집 실행 없음"}})
async def run_detail(
    run_id: UUID,
    monitor: FromDishka[PrefectMonitor],
    repository: FromDishka[MonitoringRepository],
) -> RunInfo:
    run = await monitor.run(run_id)
    run.collection = (await repository.progress([run_id])).get(run_id)
    return run


@router.get("/runs/{run_id}/articles", responses={404: {"description": "수집 실행 없음"}})
async def articles(
    run_id: UUID,
    monitor: FromDishka[PrefectMonitor],
    repository: FromDishka[MonitoringRepository],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ArticlePage:
    await monitor.run(run_id)
    return await repository.articles(run_id, limit, offset)


@router.get("/errors")
async def errors(
    repository: FromDishka[MonitoringRepository],
    query: Annotated[ErrorQuery, Query()],
) -> ErrorPage:
    return await repository.errors(query)


@router.get("/workers")
async def workers(monitor: FromDishka[PrefectMonitor]) -> WorkerSnapshot:
    return WorkerSnapshot(observed_at=datetime.now(UTC), pools=await monitor.pools())
