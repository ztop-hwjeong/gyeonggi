from curl_cffi.requests.impersonate import BrowserTypeLiteral
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class HttpSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HTTP_", extra="ignore")

    impersonate: BrowserTypeLiteral = "chrome"
    timeout_seconds: float = Field(default=30, gt=0)
    retries: int = Field(default=2, ge=0, le=10)
    retry_delay_seconds: float = Field(default=30, gt=0)
    rate_limit_timeout_seconds: float = Field(default=60, gt=0)
