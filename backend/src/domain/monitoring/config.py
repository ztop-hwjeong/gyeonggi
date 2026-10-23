from pathlib import Path

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MonitoringSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env", extra="ignore"
    )

    prefect_api_url: AnyHttpUrl
    monitoring_timeout_seconds: float = Field(default=5, gt=0, le=30)
    monitoring_flow_names: tuple[str, ...] = (
        "bigkinds-collect-list",
        "collect-article-details",
        "naver-collect-list",
        "collect-naver-cafe-details",
    )
    monitoring_pool_names: tuple[str, ...] = ("docker-collector", "windows-collector")
