from pydantic import BaseModel, Field


class PublisherCategory(BaseModel):
    code: str
    name: str
    publisher_count: int


class PublisherQuery(BaseModel):
    q: str | None = Field(default=None, max_length=100)
    category_code: str | None = None
    source: str | None = Field(default=None, max_length=50)
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


class PublisherSource(BaseModel):
    source: str
    source_code: str
    source_name: str | None
    source_category_code: str | None
    source_category_name: str | None
    area: str | None


class PublisherSourceCategory(BaseModel):
    source: str
    code: str
    name: str
    publisher_count: int
    source_code_count: int
    categories: list[PublisherCategory]


class PublisherInfo(BaseModel):
    code: str
    name: str
    category_code: str
    category_name: str
    category_source: str
    domains: list[str]
    sources: list[PublisherSource]


class PublisherPage(BaseModel):
    items: list[PublisherInfo]
    total: int


class PublisherDomain(BaseModel):
    domain: str
    publisher_code: str | None
    publisher_name: str | None
    observed_name: str | None
