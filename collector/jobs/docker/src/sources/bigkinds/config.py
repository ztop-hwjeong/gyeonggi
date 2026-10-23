from pathlib import Path

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BigKindsSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BIGKINDS_", extra="ignore")

    base_url: AnyHttpUrl = AnyHttpUrl("https://www.bigkinds.or.kr")
    rate_limit_name: str = Field(min_length=1)


class CollectionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="COLLECTION_", extra="ignore")

    output_directory: Path
