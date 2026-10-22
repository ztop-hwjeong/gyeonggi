from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from dishka import AsyncContainer
from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI

from api.health import router as health_router
from config import Settings
from container import create_container


def create_app(container: AsyncContainer | None = None) -> FastAPI:
    if container is None:
        container = create_container(Settings.model_validate({}))

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
    )
    app.include_router(health_router)
    setup_dishka(container=container, app=app)
    return app
