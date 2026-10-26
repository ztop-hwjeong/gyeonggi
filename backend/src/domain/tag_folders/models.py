from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FolderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    parent_id: UUID | None = None


class FolderUpdate(FolderCreate):
    version: int = Field(ge=1)


class FolderInfo(BaseModel):
    id: UUID
    parent_id: UUID | None
    name: str
    version: int
    tag_count: int
    material_count: int
    created_at: datetime
    updated_at: datetime


class FolderTagAttach(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tag_ids: list[str] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        if len(self.tag_ids) != len(set(self.tag_ids)):
            raise ValueError("태그 중복")
        return self


class FolderTagMove(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tag_id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,39}$")
    source_folder_id: UUID | None
    target_folder_id: UUID | None

    @model_validator(mode="after")
    def distinct_locations(self) -> Self:
        if self.source_folder_id == self.target_folder_id:
            raise ValueError("이동 전후 폴더가 같거나 모두 미분류임")
        return self


class TagInfo(BaseModel):
    id: str
    name: str
    description: str
    synonyms: list[str]
    version: int
    material_count: int
    folder_ids: list[UUID]
    created_at: datetime
    updated_at: datetime


class UnfiledTagSummary(BaseModel):
    tag_count: int
    material_count: int


class TagQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    folder_id: UUID | None = None
    include_descendants: bool = True
    unfiled: bool = False
    inclusion: Literal["all", "included", "excluded"] = "all"
    kind: Literal["news", "cafe", "blog"] | None = None

    @model_validator(mode="after")
    def folder_scope(self) -> Self:
        if self.folder_id is not None and self.unfiled:
            raise ValueError("폴더와 미분류를 함께 선택 불가")
        return self


class FolderQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inclusion: Literal["all", "included", "excluded"] = "all"
    kind: Literal["news", "cafe", "blog"] | None = None
