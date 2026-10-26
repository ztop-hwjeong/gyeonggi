from sqlalchemy import BigInteger, Column, Date, DateTime, MetaData, String, Table
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData()

materials = Table(
    "materials",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("title", String),
    Column("kind", String),
    Column("summary", String),
    Column("publisher", String),
    Column("cafe_name", String),
    Column("cafe_url", String),
    Column("blog_name", String),
    Column("blog_url", String),
    Column("published_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
    schema="dw",
)

material_sources = Table(
    "material_sources",
    metadata,
    Column("material_id", UUID(as_uuid=True)),
    Column("source", String, primary_key=True),
    Column("source_id", String, primary_key=True),
    Column("url", String),
    Column("original_url", String),
    Column("canonical_url", String),
    Column("first_seen_at", DateTime(timezone=True)),
    Column("last_seen_at", DateTime(timezone=True)),
    schema="dw",
)

article_contents = Table(
    "article_contents",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("material_id", UUID(as_uuid=True)),
    Column("source", String),
    Column("source_id", String),
    Column("content_hash", String),
    Column("title", String),
    Column("body", String),
    Column("created_at", DateTime(timezone=True)),
    schema="dw",
)

collection_rules = Table(
    "collection_rules",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("definition", JSONB),
    schema="ops",
)

collection_requests = Table(
    "collection_requests",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("rule_id", UUID(as_uuid=True)),
    Column("source", String),
    Column("mode", String),
    Column("status", String),
    Column("start_date", Date),
    Column("end_date", Date),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
    schema="ops",
)
