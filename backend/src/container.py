from collections.abc import AsyncIterator

from dishka import AsyncContainer, Provider, Scope, from_context, make_async_container, provide
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import Settings
from domain.templates.archive import TemplateArchive
from domain.templates.catalog import TemplateCatalog
from domain.templates.rendering import TemplateRenderer


class DatabaseProvider(Provider):
    settings = from_context(provides=Settings, scope=Scope.APP)

    @provide(scope=Scope.APP)
    async def engine(self, settings: Settings) -> AsyncIterator[AsyncEngine]:
        engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_timeout=3,
            connect_args={"timeout": 3, "command_timeout": 3},
            hide_parameters=True,
        )
        try:
            yield engine
        finally:
            await engine.dispose()

    @provide(scope=Scope.APP)
    def session_factory(self, engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
        return async_sessionmaker(engine, expire_on_commit=False)

    @provide(scope=Scope.REQUEST)
    async def session(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session


class TemplateProvider(Provider):
    @provide(scope=Scope.APP)
    def catalog(self, settings: Settings) -> TemplateCatalog:
        return TemplateCatalog(settings.template_directory)

    @provide(scope=Scope.APP)
    def archive(self, catalog: TemplateCatalog) -> TemplateArchive:
        return TemplateArchive(catalog)

    @provide(scope=Scope.APP)
    def renderer(self, catalog: TemplateCatalog) -> TemplateRenderer:
        return TemplateRenderer(catalog)


def create_container(settings: Settings) -> AsyncContainer:
    return make_async_container(
        DatabaseProvider(), TemplateProvider(), context={Settings: settings}
    )
