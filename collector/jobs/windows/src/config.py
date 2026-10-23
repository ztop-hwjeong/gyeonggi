from pydantic import AnyHttpUrl, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DetailSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DETAIL_", extra="ignore")

    publisher_interval_seconds: float = Field(default=10, gt=0)
    rate_limit_timeout_seconds: float = Field(default=60, gt=0)
    max_redirects: int = Field(default=5, ge=0, le=10)
    max_response_bytes: int = Field(default=10_000_000, gt=0)
    bigkinds_base_url: AnyHttpUrl = AnyHttpUrl("https://www.bigkinds.or.kr")
    bigkinds_rate_limit_name: str = Field(min_length=1)


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", hide_input_in_errors=True)

    database_host: str = Field(min_length=1)
    database_port: int = Field(gt=0, le=65535)
    database_name: str = Field(min_length=1)
    database_user: str = Field(min_length=1)
    database_password_block: str = Field(min_length=1)


class ObjectStorageSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OBJECT_STORAGE_", extra="ignore")

    endpoint_url: AnyHttpUrl
    bucket: str = Field(min_length=3)
    region: str = Field(min_length=1)
    credentials_block: str = Field(min_length=1)
    connect_timeout_seconds: int = Field(default=5, gt=0)
    read_timeout_seconds: int = Field(default=30, gt=0)


class BrowserFetchSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    browser_cdp_url: AnyHttpUrl
    browser_connect_timeout_ms: int = Field(default=5_000, gt=0)
    browser_navigation_timeout_ms: int = Field(default=30_000, gt=0)
    browser_fetch_timeout_ms: int = Field(default=30_000, gt=0)

    @field_validator("browser_cdp_url")
    @classmethod
    def require_local_cdp(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.scheme != "http" or value.host != "127.0.0.1" or not value.port:
            raise ValueError("포트를 지정한 로컬 CDP 주소 필요")
        return value


class ExtractionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EXTRACTION_", extra="ignore")

    min_body_chars: int = Field(default=200, ge=1)
    min_added_body_chars: int = Field(default=40, ge=0)
    min_summary_chars: int = Field(default=40, ge=1)
    title_similarity: float = Field(default=70, ge=0, le=100)
    snippet_similarity: float = Field(default=85, ge=0, le=100)
    snippet_window_chars: int = Field(default=60, ge=20)
    snippet_step_chars: int = Field(default=40, ge=10)
    snippet_match_fraction: float = Field(default=0.5, gt=0, le=1)
    adaptive_similarity: int = Field(default=60, ge=0, le=100)
    training_similarity: float = Field(default=80, ge=0, le=100)
    max_dom_candidates: int = Field(default=2_000, ge=1)
