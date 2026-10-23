from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class TemplateReference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    version: str = Field(pattern=r"^[1-9][0-9]*\.[0-9]+\.[0-9]+$")


class TemplateSheet(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    name: str = Field(min_length=1)


class TemplateVersion(TemplateReference):
    name: str = Field(min_length=1)
    filename: str = Field(pattern=r"^[a-zA-Z0-9_-]+\.xlsx$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sheets: Annotated[tuple[TemplateSheet, ...], Field(min_length=1)]
    variables: dict[str, JsonValue]
    engine: Literal["templexl"]
    tables: dict[str, Annotated[tuple[str, ...], Field(min_length=1)]]
