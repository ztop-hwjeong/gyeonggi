from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class RelevanceInput(BaseModel):
    run_id: UUID
    title: str
    body: str
    criteria: str


class RelevanceDraft(BaseModel):
    relevance: Literal["related", "unrelated", "uncertain"]
    reason: str = Field(min_length=1, max_length=300)
    evidence: list[str] = Field(max_length=5)

    @field_validator("evidence")
    @classmethod
    def nonempty(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("빈 근거 문장 불가")
        return values
