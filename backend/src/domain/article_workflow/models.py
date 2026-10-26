from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

type Decision = Literal["include", "exclude"]
type TargetKind = Literal["policy", "regular", "current_issue", "leader_message"]


class TargetWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: TargetKind
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)


class TargetUpdate(TargetWrite):
    version: int = Field(ge=1)


class TargetInfo(TargetWrite):
    id: UUID
    version: int
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class FilterConditions(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    all_terms: list[str] = Field(default_factory=list, alias="all", max_length=20)
    any_terms: list[str] = Field(default_factory=list, alias="any", max_length=20)
    none_terms: list[str] = Field(default_factory=list, alias="none", max_length=20)

    @field_validator("all_terms", "any_terms", "none_terms")
    @classmethod
    def terms(cls, values: list[str]) -> list[str]:
        terms = [" ".join(value.split()) for value in values]
        if any(not term or len(term) > 100 for term in terms):
            raise ValueError("키워드는 공백 아닌 100자 이하 문구 필요")
        return list(dict.fromkeys(terms))

    @model_validator(mode="after")
    def has_condition(self) -> Self:
        if not (self.all_terms or self.any_terms or self.none_terms):
            raise ValueError("최소 한 가지 키워드 조건 필요")
        return self


class FilterRuleWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    target_id: UUID | None = None
    priority: int = Field(ge=-10000, le=10000)
    decision: Decision
    conditions: FilterConditions
    enabled: bool = True


class FilterRuleUpdate(FilterRuleWrite):
    version: int = Field(ge=1)


class FilterRuleInfo(FilterRuleWrite):
    id: UUID
    version: int
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DecisionWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    decision: Literal["include", "exclude", "release"]
    reason: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def reason_for_override(self) -> Self:
        if self.decision != "release" and not self.reason:
            raise ValueError("수동 판단 사유 필요")
        return self


class DecisionInfo(BaseModel):
    article_id: UUID
    target_id: UUID | None = None
    decision: Decision
    origin: Literal["auto", "manual"]
    reason: str
    matched_terms: list[str] = Field(default_factory=list)
    rule_id: UUID | None = None
    rule_version: int | None = None
    updated_at: datetime | None = None


class DecisionHistory(BaseModel):
    id: int
    article_id: UUID
    target_id: UUID | None
    previous_decision: Decision | None
    decision: Decision | None
    action: Literal["evaluate", "override", "release"]
    origin: Literal["auto", "manual"]
    reason: str
    matched_terms: list[str]
    rule_id: UUID | None
    rule_version: int | None
    created_at: datetime


class EvaluationResult(BaseModel):
    article_id: UUID
    inclusion: DecisionInfo
    targets: list[DecisionInfo]
    matched_rule_ids: list[UUID]


class ReapplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["all", "target", "selected"]
    target_id: UUID | None = None
    article_ids: list[UUID] | None = None

    @model_validator(mode="after")
    def valid_scope(self) -> Self:
        if self.scope == "target" and self.target_id is not None and self.article_ids is None:
            return self
        if self.scope == "selected" and self.article_ids and self.target_id is None:
            return self
        if self.scope == "all" and self.target_id is None and self.article_ids is None:
            return self
        raise ValueError("재적용 범위와 대상 불일치")


class ReapplyResult(BaseModel):
    processed_count: int
