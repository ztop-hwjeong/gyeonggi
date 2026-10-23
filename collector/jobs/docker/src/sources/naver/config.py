from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class NaverSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NAVER_", extra="ignore")

    base_url: AnyHttpUrl = AnyHttpUrl("https://naverapihub.apigw.ntruss.com")
    credentials_block: str = Field(min_length=1)
    rate_limit_name: str = Field(min_length=1)
    daily_request_limit: int = Field(default=1000, ge=1, le=25000)
    overlap_pages: int = Field(default=1, ge=0, le=3)
    date_overlap_days: int = Field(default=1, ge=1, le=30)
    error_pause_seconds: int = Field(default=900, ge=1)


class NaverCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    client_id: SecretStr
    client_secret: SecretStr
