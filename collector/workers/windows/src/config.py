from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    AnyHttpUrl,
    BaseModel,
    DirectoryPath,
    Field,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


def validate_local_cdp(value: AnyHttpUrl) -> AnyHttpUrl:
    if value.scheme != "http" or value.host != "127.0.0.1" or not value.port:
        raise ValueError("CDP 주소는 포트를 지정한 로컬 HTTP 주소 필요")
    return value


type LocalCdpUrl = Annotated[AnyHttpUrl, AfterValidator(validate_local_cdp)]


class EnvironmentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True
    )


class BrowserSettings(EnvironmentSettings):
    browser_cdp_url: LocalCdpUrl
    browser_connect_timeout_ms: int = Field(default=5_000, gt=0)
    browser_navigation_timeout_ms: int = Field(default=30_000, gt=0)


class RecoverySettings(EnvironmentSettings):
    browser_operation_attempts: int = Field(default=3, ge=1)
    browser_operation_retry_delay: float = Field(default=3, gt=0)


class EdgeSettings(EnvironmentSettings):
    browser_cdp_url: LocalCdpUrl
    browser_profile_directory: Path
    edge_default_profile_directory: Path
    browser_restart_delay: float = Field(default=3, gt=0)
    browser_launch_timeout_ms: int = Field(default=30_000, gt=0)

    @field_validator(
        "browser_profile_directory",
        "edge_default_profile_directory",
    )
    @classmethod
    def resolve_directory(cls, value: Path) -> Path:
        return value.resolve()

    @model_validator(mode="after")
    def validate_browser_profile(self) -> Self:
        if self.browser_profile_directory.is_relative_to(self.edge_default_profile_directory):
            raise ValueError("Edge 기본 프로필 대신 수집 전용 프로필 경로 지정 필요")
        return self


class WorkerSettings(EnvironmentSettings):
    collector_directory: DirectoryPath
    runtime_directory: Path
    prefect_api_url: AnyHttpUrl
    worker_pool: str = Field(min_length=1)
    worker_limit: int = Field(ge=1)
    worker_restart_delay: float = Field(default=10, gt=0)
    process_stop_timeout: float = Field(default=5, gt=0)

    @field_validator("collector_directory", "runtime_directory")
    @classmethod
    def resolve_directory(cls, value: Path) -> Path:
        return value.resolve()


class RuntimeSettings(BaseModel):
    worker: WorkerSettings
    edge: EdgeSettings
    browser: BrowserSettings
    recovery: RecoverySettings

    @classmethod
    def load(cls, values: Mapping[str, object]) -> Self:
        return cls(
            worker=WorkerSettings.model_validate(values),
            edge=EdgeSettings.model_validate(values),
            browser=BrowserSettings.model_validate(values),
            recovery=RecoverySettings.model_validate(values),
        )
