from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from dishka import AsyncContainer
from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api.collection import router as collection_router
from api.health import router as health_router
from api.monitoring import router as monitoring_router
from api.templates import router as templates_router
from config import Settings
from container import create_container
from domain.collection.errors import (
    CollectionConflictError,
    CollectionNotFoundError,
    CollectionUnavailableError,
)
from domain.monitoring.errors import MonitoringUnavailableError, RunNotFoundError


def create_app(container: AsyncContainer | None = None) -> FastAPI:
    root_path = ""
    if container is None:
        settings = Settings.model_validate({})
        root_path = settings.api_root_path
        container = create_container(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        try:
            yield
        finally:
            await container.close()

    app = FastAPI(
        title="경기교육 정책 홍보 분석 API",
        version="0.1.0",
        lifespan=lifespan,
        root_path=root_path,
    )
    app.include_router(health_router)
    app.include_router(templates_router)
    app.include_router(monitoring_router)
    app.include_router(collection_router)

    @app.exception_handler(CollectionNotFoundError)
    async def collection_not_found(request: Request, error: CollectionNotFoundError):
        return JSONResponse(status_code=404, content={"detail": str(error)})

    @app.exception_handler(CollectionConflictError)
    async def collection_conflict(request: Request, error: CollectionConflictError):
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(CollectionUnavailableError)
    async def collection_unavailable(request: Request, error: CollectionUnavailableError):
        return JSONResponse(status_code=503, content={"detail": str(error)})

    @app.exception_handler(MonitoringUnavailableError)
    async def monitoring_unavailable(request: Request, error: MonitoringUnavailableError):
        return JSONResponse(status_code=503, content={"detail": str(error)})

    @app.exception_handler(RunNotFoundError)
    async def run_not_found(request: Request, error: RunNotFoundError):
        return JSONResponse(status_code=404, content={"detail": "수집 실행 없음"})

    setup_dishka(container=container, app=app)
    return app
