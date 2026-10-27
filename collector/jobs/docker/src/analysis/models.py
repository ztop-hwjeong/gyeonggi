from typing import Literal
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AnalysisSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", hide_input_in_errors=True)

    openai_api_key_block: str = Field(default="openai-api-key", min_length=1)
    backend_api_url: AnyHttpUrl


class AnalysisDispatchSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ANALYSIS_", extra="ignore")

    deployment_name: str = "analyze-stored-article/stored-article-analysis"


class Article(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    article_id: UUID
    source: str
    source_id: str
    content_hash: str
    title: str
    body: str


class ModelDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tags: list[str] = Field(max_length=20)
    sentiment: Literal["긍정", "중립", "부정"]
    mixed_sentiment: bool
    sentiment_reason: str = Field(min_length=1, max_length=160)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, tags: list[str]) -> list[str]:
        normalized = [" ".join(tag.split()) for tag in tags]
        if any(not tag or len(tag) > 80 for tag in normalized):
            raise ValueError("태그는 공백이 아닌 80자 이하 문구 필요")
        return list(dict.fromkeys(normalized))

    @field_validator("sentiment_reason")
    @classmethod
    def normalize_reason(cls, reason: str) -> str:
        normalized = " ".join(reason.split())
        if not normalized:
            raise ValueError("최종 논조 근거 필요")
        return normalized
