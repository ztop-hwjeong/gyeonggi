from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_host: str
    database_port: int = Field(ge=1, le=65535)
    database_name: str
    database_user: str
    database_password: SecretStr
    api_root_path: str = ""
    template_directory: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parents[1] / "templates"
    )

    @property
    def database_url(self) -> URL:
        return URL.create(
            "postgresql+asyncpg",
            username=self.database_user,
            password=self.database_password.get_secret_value(),
            host=self.database_host,
            port=self.database_port,
            database=self.database_name,
        )
