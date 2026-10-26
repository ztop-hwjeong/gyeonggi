from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import cast

from collector_storage.config import DatabaseSettings
from dishka import AsyncContainer, Provider, Scope, make_async_container, provide
from prefect.blocks.system import Secret
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from analysis.cache import PostgresResponseCache
from analysis.client import OpenAIArticleAnalyzer
from analysis.models import AnalysisDispatchSettings, AnalysisSettings
from analysis.repository import AnalysisRepository


@dataclass(frozen=True)
class DatabaseCredentials:
    password: SecretStr


@dataclass(frozen=True)
class ModelCredentials:
    api_key: SecretStr


class AnalysisProvider(Provider):
    @provide(scope=Scope.APP)
    def database_settings(self) -> DatabaseSettings:
        return DatabaseSettings.model_validate({})

    @provide(scope=Scope.APP)
    def analysis_settings(self) -> AnalysisSettings:
        return AnalysisSettings.model_validate({})

    @provide(scope=Scope.APP)
    def dispatch_settings(self) -> AnalysisDispatchSettings:
        return AnalysisDispatchSettings.model_validate({})

    @provide(scope=Scope.APP)
    async def database_credentials(self, settings: DatabaseSettings) -> DatabaseCredentials:
        value = cast(Secret, await Secret.aload(settings.database_password_block)).get()
        return DatabaseCredentials(SecretStr(cast(str, value)))

    @provide(scope=Scope.APP)
    async def model_credentials(self, settings: AnalysisSettings) -> ModelCredentials:
        value = cast(Secret, await Secret.aload(settings.openai_api_key_block)).get()
        return ModelCredentials(SecretStr(cast(str, value)))

    @staticmethod
    def url(settings: DatabaseSettings, credentials: DatabaseCredentials) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username=settings.database_user,
            password=credentials.password.get_secret_value(),
            host=settings.database_host,
            port=settings.database_port,
            database=settings.database_name,
        )

    @provide(scope=Scope.APP)
    async def async_engine(
        self, settings: DatabaseSettings, credentials: DatabaseCredentials
    ) -> AsyncIterator[AsyncEngine]:
        engine = create_async_engine(
            self.url(settings, credentials),
            pool_pre_ping=True,
            hide_parameters=True,
            connect_args={"connect_timeout": 5, "options": "-c statement_timeout=5000"},
        )
        try:
            yield engine
        finally:
            await engine.dispose()

    @provide(scope=Scope.APP)
    def sync_engine(
        self, settings: DatabaseSettings, credentials: DatabaseCredentials
    ) -> Iterator[Engine]:
        engine = create_engine(
            self.url(settings, credentials),
            pool_pre_ping=True,
            hide_parameters=True,
            connect_args={"connect_timeout": 5, "options": "-c statement_timeout=5000"},
        )
        try:
            yield engine
        finally:
            engine.dispose()

    @provide(scope=Scope.APP)
    def sessions(self, engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
        return async_sessionmaker(engine, expire_on_commit=False)

    @provide(scope=Scope.REQUEST)
    def repository(self, sessions: async_sessionmaker[AsyncSession]) -> AnalysisRepository:
        return AnalysisRepository(sessions)

    @provide(scope=Scope.REQUEST)
    def cache(self, engine: Engine) -> PostgresResponseCache:
        return PostgresResponseCache(engine)

    @provide(scope=Scope.REQUEST)
    def analyzer(
        self, credentials: ModelCredentials, cache: PostgresResponseCache
    ) -> OpenAIArticleAnalyzer:
        return OpenAIArticleAnalyzer(credentials.api_key, cache)


def create_analysis_container() -> AsyncContainer:
    return make_async_container(AnalysisProvider())
