from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
