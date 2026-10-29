from sqlalchemy import Column, Date, DateTime, FetchedValue, MetaData, Table, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData()

blog_posts = Table(
    "blog_posts",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("title", Text),
    Column("summary", Text),
    Column("blog_name", Text),
    Column("blog_url", Text),
    Column("published_on", Date),
    Column("published_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
    schema="dw",
)
blog_sources = Table(
    "blog_sources",
    metadata,
    Column("blog_post_id", UUID(as_uuid=True)),
    Column("source", Text, primary_key=True),
    Column("source_id", Text, primary_key=True),
    Column("url", Text),
    Column("original_url", Text),
    Column("first_seen_at", DateTime(timezone=True)),
    schema="dw",
)
blog_contents = Table(
    "blog_contents",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=FetchedValue()),
    Column("blog_post_id", UUID(as_uuid=True)),
    Column("source", Text),
    Column("source_id", Text),
    Column("content_hash", Text),
    Column("title", Text),
    Column("body", Text),
    Column("stage", Text),
    Column("run_id", UUID(as_uuid=True)),
    Column("provenance", JSONB),
    Column("original_published_on", Date),
    Column("original_published_at", DateTime(timezone=True)),
    Column("original_modified_on", Date),
    Column("original_modified_at", DateTime(timezone=True)),
    Column("collected_at", DateTime(timezone=True)),
    schema="dw",
)
detail_runs = Table(
    "blog_detail_runs",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("summary", JSONB),
    schema="ops",
)
detail_results = Table(
    "blog_detail_results",
    metadata,
    Column("run_id", UUID(as_uuid=True), primary_key=True),
    Column("source", Text, primary_key=True),
    Column("source_id", Text, primary_key=True),
    Column("result", JSONB),
    Column("created_at", DateTime(timezone=True)),
    schema="st",
)
responses = Table(
    "blog_responses",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("run_id", UUID(as_uuid=True)),
    Column("source", Text),
    Column("source_id", Text),
    Column("stage", Text),
    Column("seed", JSONB),
    Column("metadata", JSONB),
    Column("raw_object", JSONB),
    schema="st",
)
search_run_items = Table(
    "search_run_items",
    metadata,
    Column("run_id", UUID(as_uuid=True), primary_key=True),
    Column("source_id", Text, primary_key=True),
    schema="st",
)
