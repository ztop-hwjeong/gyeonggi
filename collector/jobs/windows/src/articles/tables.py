from sqlalchemy import BigInteger, Column, Date, DateTime, MetaData, String, Table, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData()

publishers = Table(
    "publishers",
    metadata,
    Column("code", Text, primary_key=True),
    Column("name", Text),
    Column("category_code", Text),
    schema="dw",
)
publisher_domains = Table(
    "publisher_domains",
    metadata,
    Column("domain", Text, primary_key=True),
    Column("publisher_code", Text),
    schema="dw",
)
article_browser_policies = Table(
    "article_browser_policies",
    metadata,
    Column("domain", Text, primary_key=True),
    Column("browser_mode", Text),
    Column("reason", Text),
    Column("evidence", JSONB),
    Column("updated_at", DateTime(timezone=True)),
    schema="ops",
)
publisher_source_codes = Table(
    "publisher_source_codes",
    metadata,
    Column("source", Text, primary_key=True),
    Column("source_code", Text, primary_key=True),
    Column("publisher_code", Text),
    schema="dw",
)

search_items = Table(
    "search_items",
    metadata,
    Column("provider", Text),
    Column("channel", Text),
    Column("source_id", Text),
    Column("article_id", UUID(as_uuid=True)),
    Column("data", JSONB),
    Column("first_seen_at", DateTime(timezone=True)),
    schema="dw",
)
news_items = Table(
    "news_items",
    metadata,
    Column("source", Text),
    Column("source_id", Text),
    Column("data", JSONB),
    Column("article_id", UUID(as_uuid=True)),
    Column("first_seen_at", DateTime(timezone=True)),
    schema="dw",
)
articles = Table(
    "articles",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("publisher", Text),
    Column("publisher_code", Text),
    schema="dw",
)
search_run_items = Table(
    "search_run_items",
    metadata,
    Column("run_id", UUID(as_uuid=True)),
    Column("source_id", Text),
    schema="st",
)

detail_runs = Table(
    "article_detail_runs",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("summary", JSONB),
    Column("created_at", DateTime(timezone=True)),
    schema="ops",
)
responses = Table(
    "article_responses",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("run_id", UUID(as_uuid=True)),
    Column("source_id", Text),
    Column("stage", String),
    Column("seed", JSONB),
    Column("metadata", JSONB),
    Column("raw_object", JSONB),
    schema="st",
)
attempts = Table(
    "article_detail_attempts",
    metadata,
    Column("run_id", UUID(as_uuid=True), primary_key=True),
    Column("source_id", Text, primary_key=True),
    Column("stage", String, primary_key=True),
    Column("result", JSONB),
    schema="st",
)
detail_results = Table(
    "article_detail_results",
    metadata,
    Column("run_id", UUID(as_uuid=True), primary_key=True),
    Column("source_id", Text, primary_key=True),
    Column("result", JSONB),
    schema="st",
)
article_contents = Table(
    "article_contents",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("article_id", UUID(as_uuid=True)),
    Column("source", String),
    Column("source_id", String),
    Column("content_hash", String),
    Column("title", Text),
    Column("body", Text),
    Column("stage", String),
    Column("run_id", UUID(as_uuid=True)),
    Column("provenance", JSONB),
    Column("original_published_on", Date),
    Column("original_published_at", DateTime(timezone=True)),
    Column("original_modified_on", Date),
    Column("original_modified_at", DateTime(timezone=True)),
    Column("collected_at", DateTime(timezone=True)),
    schema="dw",
)
adaptive_profiles = Table(
    "publisher_adaptive_profiles",
    metadata,
    Column("scope", String, primary_key=True),
    Column("identifier", String, primary_key=True),
    Column("properties", JSONB),
    Column("context", JSONB),
    schema="ops",
)
adaptive_history = Table(
    "publisher_adaptive_history",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("scope", String),
    Column("identifier", String),
    Column("properties", JSONB),
    Column("context", JSONB),
    schema="ops",
)
