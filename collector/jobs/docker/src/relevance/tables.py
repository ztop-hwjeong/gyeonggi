from sqlalchemy import BigInteger, Column, DateTime, MetaData, Table, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()
report_relevance_runs = Table(
    "report_relevance_runs",
    metadata,
    Column("id", Uuid),
    Column("content_id", BigInteger),
    Column("content_hash", Text),
    Column("title", Text),
    Column("criteria", Text),
    Column("model", Text),
    Column("prompt", Text),
    Column("prompt_hash", Text),
    Column("status", Text),
    Column("relevance", Text),
    Column("reason", Text),
    Column("evidence", JSONB),
    Column("usage", JSONB),
    Column("error", Text),
    Column("flow_run_id", Uuid),
    Column("submission_attempts", BigInteger),
    Column("lease_expires_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
    schema="ops",
)
article_contents = Table(
    "article_contents", metadata, Column("id", BigInteger), Column("body", Text), schema="dw"
)
