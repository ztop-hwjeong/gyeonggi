from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ControlSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CONTROL_", extra="ignore")
    deployment_name: str = "managed-collection/managed-collection"
    dispatch_batch_size: int = Field(default=20, ge=1, le=100)
    bigkinds_max_pages_per_day: int = Field(default=100, ge=1, le=1000)


class Definition(BaseModel):
    name: str
    terms: tuple[str, ...]
    sources: tuple[str, ...]
    enabled: bool
    interval_minutes: int


class ManagedRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: UUID
    source: Literal["bigkinds", "naver_news", "naver_blog", "naver_cafearticle"]
    mode: Literal["preview", "incremental", "backfill"]
    definition: Definition
    start_date: date
    end_date: date
    status: str


class CollectionCancelled(Exception):
    pass
