from collections.abc import Iterator
from dataclasses import dataclass
from typing import cast

from collector_storage.config import DatabaseSettings
from dishka import Container, Provider, Scope, make_container, provide
from prefect.blocks.system import Secret
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine

from control.repository import ControlRepository


@dataclass(frozen=True)
class DatabaseCredentials:
    password: SecretStr


class ControlProvider(Provider):
    @provide(scope=Scope.APP)
    def database_settings(self) -> DatabaseSettings:
        return DatabaseSettings.model_validate({})

    @provide(scope=Scope.APP)
    def database_credentials(self, settings: DatabaseSettings) -> DatabaseCredentials:
        value = cast(Secret, Secret.load(settings.database_password_block)).get()
        return DatabaseCredentials(SecretStr(cast(str, value)))

    @provide(scope=Scope.APP)
    def engine(
        self, settings: DatabaseSettings, credentials: DatabaseCredentials
    ) -> Iterator[Engine]:
        engine = create_engine(
            URL.create(
                "postgresql+psycopg",
                username=settings.database_user,
                password=credentials.password.get_secret_value(),
                host=settings.database_host,
                port=settings.database_port,
                database=settings.database_name,
            ),
            pool_pre_ping=True,
            hide_parameters=True,
            connect_args={"connect_timeout": 5},
        )
        try:
            yield engine
        finally:
            engine.dispose()

    @provide(scope=Scope.REQUEST)
    def repository(
        self, settings: DatabaseSettings, credentials: DatabaseCredentials, engine: Engine
    ) -> ControlRepository:
        return ControlRepository(settings, credentials.password, engine)


def create_control_container() -> Container:
    return make_container(ControlProvider())
