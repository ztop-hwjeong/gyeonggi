from sqlalchemy import BigInteger, Column, DateTime, Float, MetaData, Table, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

article_contents = Table(
    "article_contents",
    metadata,
    Column("id", BigInteger),
    Column("article_id", Uuid),
    Column("source", Text),
    Column("source_id", Text),
    Column("content_hash", Text),
    Column("title", Text),
    Column("body", Text),
    Column("created_at", DateTime(timezone=True)),
    schema="dw",
)

articles = Table(
    "articles",
    metadata,
    Column("id", Uuid),
    Column("publisher", Text),
    schema="dw",
)

reprints = Table(
    "article_reprints",
    metadata,
    Column("article_a_id", Uuid),
    Column("article_b_id", Uuid),
    Column("article_a_content_hash", Text),
    Column("article_b_content_hash", Text),
    Column("body_similarity", Float),
    Column("matching_basis", Text),
    Column("checked_at", DateTime(timezone=True)),
    schema="ops",
)

runs = Table(
    "analysis_runs",
    metadata,
    Column("id", Uuid),
    Column("article_id", Uuid),
    Column("source", Text),
    Column("source_id", Text),
    Column("content_hash", Text),
    Column("model", Text),
    Column("prompt", Text),
    Column("prompt_hash", Text),
    Column("status", Text),
    Column("catalog_snapshot", JSONB),
    Column("model_draft", JSONB),
    Column("usage", JSONB),
    Column("error", Text),
    Column("lease_expires_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
    schema="ops",
)

attempts = Table(
    "analysis_attempts",
    metadata,
    Column("id", BigInteger),
    Column("run_id", Uuid),
    Column("prefect_flow_run_id", Uuid),
    Column("prefect_task_run_id", Uuid),
    Column("status", Text),
    Column("model", Text),
    Column("prompt", Text),
    Column("prompt_hash", Text),
    Column("model_draft", JSONB),
    Column("usage", JSONB),
    Column("error", Text),
    Column("finished_at", DateTime(timezone=True)),
    schema="ops",
)

queue = Table(
    "analysis_queue",
    metadata,
    Column("article_id", Uuid),
    Column("source", Text),
    Column("source_id", Text),
    Column("content_hash", Text),
    Column("status", Text),
    Column("flow_run_id", Uuid),
    Column("error", Text),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
    schema="ops",
)

queue_keys = Table(
    "analysis_queue_keys",
    metadata,
    Column("article_id", Uuid),
    Column("source", Text),
    Column("source_id", Text),
    Column("content_hash", Text),
    schema="ops",
)

response_cache = Table(
    "analysis_response_cache",
    metadata,
    Column("cache_key", Text),
    Column("prompt", Text),
    Column("llm_string", Text),
    Column("generations", JSONB),
    schema="ops",
)
