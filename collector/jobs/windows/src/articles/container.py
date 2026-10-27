from collections.abc import Iterator
from dataclasses import dataclass
from typing import cast

from collector_storage.config import DatabaseSettings, ObjectStorageSettings
from collector_storage.objects import ObjectCredentials, RawObjectStore
from dishka import Container, Provider, Scope, make_container, provide
from prefect.blocks.system import Secret
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine

from articles.storage import DetailRepository


@dataclass(frozen=True)
class DatabaseCredentials:
    password: SecretStr


@dataclass(frozen=True)
class StorageCredentials:
    value: ObjectCredentials


class DetailProvider(Provider):
    @provide(scope=Scope.APP)
    def database_settings(self) -> DatabaseSettings:
        return DatabaseSettings.model_validate({})

    @provide(scope=Scope.APP)
    def object_settings(self) -> ObjectStorageSettings:
        return ObjectStorageSettings.model_validate({})

    @provide(scope=Scope.APP)
    def database_credentials(self, settings: DatabaseSettings) -> DatabaseCredentials:
        value = cast(Secret, Secret.load(settings.database_password_block)).get()
        return DatabaseCredentials(SecretStr(cast(str, value)))

    @provide(scope=Scope.APP)
    def storage_credentials(self, settings: ObjectStorageSettings) -> StorageCredentials:
        value = cast(Secret, Secret.load(settings.credentials_block)).get()
        return StorageCredentials(ObjectCredentials.model_validate(value))

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
    def engine(
        self, settings: DatabaseSettings, credentials: DatabaseCredentials
    ) -> Iterator[Engine]:
        engine = create_engine(
            self.url(settings, credentials),
            pool_pre_ping=True,
            hide_parameters=True,
            connect_args={"connect_timeout": 5},
        )
        try:
            yield engine
        finally:
            engine.dispose()

    @provide(scope=Scope.APP)
    def objects(
        self, settings: ObjectStorageSettings, credentials: StorageCredentials
    ) -> Iterator[RawObjectStore]:
        with RawObjectStore(settings, credentials.value) as objects:
            yield objects

    @provide(scope=Scope.REQUEST)
    def repository(self, engine: Engine, objects: RawObjectStore) -> DetailRepository:
        return DetailRepository(engine, objects)


def create_detail_container() -> Container:
    return make_container(DetailProvider())
