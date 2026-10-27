from collections.abc import AsyncIterator

import httpx2
from dishka import AsyncContainer, Provider, Scope, from_context, make_async_container, provide
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import Settings
from domain.analysis.application import AnalysisApplication
from domain.analysis.registry import TopicRegistry
from domain.article_workflow.relations import ArticleRelations
from domain.article_workflow.repository import ArticleWorkflow
from domain.collection.reporting import CollectionReporting
from domain.collection.repository import CollectionRepository
from domain.events.repository import EventRepository
from domain.monitoring.config import MonitoringSettings
from domain.monitoring.errors import MonitoringUnavailableError
from domain.monitoring.prefect import PrefectMonitor
from domain.monitoring.repository import MonitoringRepository
from domain.tag_folders.material_tags import MaterialTags
from domain.tag_folders.repository import TagFolderRepository
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


class CollectionProvider(Provider):
    @provide(scope=Scope.REQUEST)
    def reporting(self, session: AsyncSession) -> CollectionReporting:
        return CollectionReporting(session)

    @provide(scope=Scope.REQUEST)
    def collections(self, session: AsyncSession) -> CollectionRepository:
        return CollectionRepository(session)


class AnalysisProvider(Provider):
    @provide(scope=Scope.REQUEST)
    def article_relations(self, session: AsyncSession) -> ArticleRelations:
        return ArticleRelations(session)

    @provide(scope=Scope.REQUEST)
    def article_workflow(self, session: AsyncSession) -> ArticleWorkflow:
        return ArticleWorkflow(session)

    @provide(scope=Scope.REQUEST)
    def topic_registry(self, session: AsyncSession) -> TopicRegistry:
        return TopicRegistry(session)

    @provide(scope=Scope.REQUEST)
    def tag_folders(self, session: AsyncSession) -> TagFolderRepository:
        return TagFolderRepository(session)

    @provide(scope=Scope.REQUEST)
    def material_tags(self, session: AsyncSession) -> MaterialTags:
        return MaterialTags(session)

    @provide(scope=Scope.REQUEST)
    def events(self, session: AsyncSession) -> EventRepository:
        return EventRepository(session)

    @provide(scope=Scope.REQUEST)
    def application(
        self, registry: TopicRegistry, workflow: ArticleWorkflow
    ) -> AnalysisApplication:
        return AnalysisApplication(registry, workflow)


class MonitoringProvider(Provider):
    @provide(scope=Scope.APP)
    def settings(self) -> MonitoringSettings:
        try:
            return MonitoringSettings.model_validate({})
        except ValidationError as error:
            raise MonitoringUnavailableError("Prefect 모니터링 설정 오류") from error

    @provide(scope=Scope.APP)
    async def monitor(self, settings: MonitoringSettings) -> AsyncIterator[PrefectMonitor]:
        async with httpx2.AsyncClient(
            base_url=str(settings.prefect_api_url).rstrip("/") + "/",
            timeout=settings.monitoring_timeout_seconds,
            trust_env=False,
        ) as client:
            yield PrefectMonitor(client, settings)

    @provide(scope=Scope.REQUEST)
    def repository(self, session: AsyncSession) -> MonitoringRepository:
        return MonitoringRepository(session)


def create_container(settings: Settings) -> AsyncContainer:
    return make_async_container(
        DatabaseProvider(),
        TemplateProvider(),
        CollectionProvider(),
        AnalysisProvider(),
        MonitoringProvider(),
        context={Settings: settings},
    )
