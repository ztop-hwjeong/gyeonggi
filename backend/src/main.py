from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from dishka import AsyncContainer
from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api.analysis_registry import router as analysis_registry_router
from api.article_workflow import router as article_workflow_router
from api.collection import router as collection_router
from api.events import router as events_router
from api.health import router as health_router
from api.monitoring import router as monitoring_router
from api.tag_folders import router as tag_folders_router
from api.templates import router as templates_router
from config import Settings
from container import create_container
from domain.analysis.registry import (
    TopicRegistryConflictError,
    TopicRegistryError,
    TopicRegistryInvalidMaterialError,
    TopicRegistryNotFoundError,
)
from domain.collection.errors import (
    CollectionConflictError,
    CollectionInvalidMaterialError,
    CollectionNotFoundError,
    CollectionUnavailableError,
)
from domain.monitoring.errors import MonitoringUnavailableError, RunNotFoundError
from domain.tag_folders.repository import (
    TagFolderConflictError,
    TagFolderError,
    TagFolderNotFoundError,
)


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
    app.include_router(analysis_registry_router)
    app.include_router(article_workflow_router)
    app.include_router(tag_folders_router)
    app.include_router(events_router)

    @app.exception_handler(CollectionNotFoundError)
    async def collection_not_found(request: Request, error: CollectionNotFoundError):
        return JSONResponse(status_code=404, content={"detail": str(error)})

    @app.exception_handler(CollectionInvalidMaterialError)
    async def collection_invalid_material(request: Request, error: CollectionInvalidMaterialError):
        return JSONResponse(status_code=422, content={"detail": str(error)})

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

    @app.exception_handler(TopicRegistryNotFoundError)
    async def topic_not_found(request: Request, error: TopicRegistryNotFoundError):
        return JSONResponse(status_code=404, content={"detail": str(error)})

    @app.exception_handler(TopicRegistryConflictError)
    async def topic_conflict(request: Request, error: TopicRegistryConflictError):
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(TopicRegistryInvalidMaterialError)
    async def topic_invalid_material(request: Request, error: TopicRegistryInvalidMaterialError):
        return JSONResponse(status_code=422, content={"detail": str(error)})

    @app.exception_handler(TopicRegistryError)
    async def topic_unavailable(request: Request, error: TopicRegistryError):
        return JSONResponse(status_code=503, content={"detail": str(error)})

    @app.exception_handler(TagFolderNotFoundError)
    async def tag_folder_not_found(request: Request, error: TagFolderNotFoundError):
        return JSONResponse(status_code=404, content={"detail": str(error)})

    @app.exception_handler(TagFolderConflictError)
    async def tag_folder_conflict(request: Request, error: TagFolderConflictError):
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(TagFolderError)
    async def tag_folder_unavailable(request: Request, error: TagFolderError):
        return JSONResponse(status_code=503, content={"detail": str(error)})

    setup_dishka(container=container, app=app)
    return app
