from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BigKindsRateLimitSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BIGKINDS_", extra="ignore")

    rate_limit_name: str = Field(default="bigkinds-http", min_length=1)
    request_interval_seconds: float = Field(default=10, gt=0)
