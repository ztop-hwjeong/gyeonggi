from typing import Literal
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AnalysisSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", hide_input_in_errors=True)

    openai_api_key_block: str = Field(default="openai-api-key", min_length=1)
    backend_api_url: AnyHttpUrl


class AnalysisDispatchSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ANALYSIS_", extra="ignore")

    deployment_name: str = "analyze-stored-article/stored-article-analysis"


class Topic(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    description: str
    synonyms: list[str]


class Article(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    article_id: UUID
    source: str
    source_id: str
    content_hash: str
    title: str
    body: str


class ArticleProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic_ids: list[str] = Field(max_length=20)
    keywords: list[str] = Field(max_length=20)
    sentiment: Literal["", "긍정", "중립", "부정"]
    quote: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=500)
    review_required: bool


class TopicCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=400)
    quote: str = Field(min_length=1, max_length=500)


class ModelDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    article: ArticleProposal
    topic_candidates: list[TopicCandidate] = Field(max_length=10)
