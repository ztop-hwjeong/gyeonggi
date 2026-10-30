from sqlalchemy import Boolean, Column, Date, DateTime, Integer, MetaData, Table, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData()

collection_request_items = Table(
    "collection_request_items",
    metadata,
    Column("request_id", UUID(as_uuid=True), primary_key=True),
    Column("source_id", Text, primary_key=True),
    Column("data", JSONB),
    schema="st",
)

collection_rules = Table(
    "collection_rules",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("version", Integer),
    Column("definition", JSONB),
    schema="ops",
)
collection_rule_versions = Table(
    "collection_rule_versions",
    metadata,
    Column("rule_id", UUID(as_uuid=True), primary_key=True),
    Column("version", Integer, primary_key=True),
    Column("definition", JSONB),
    schema="ops",
)
collection_rule_targets = Table(
    "collection_rule_targets",
    metadata,
    Column("rule_id", UUID(as_uuid=True), primary_key=True),
    Column("target_id", UUID(as_uuid=True), primary_key=True),
    schema="ops",
)
analysis_targets = Table(
    "analysis_targets",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("kind", Text),
    Column("name", Text),
    Column("archived_at", DateTime(timezone=True)),
    Column("collection_enabled", Boolean),
    schema="ops",
)
collection_requests = Table(
    "collection_requests",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("rule_id", UUID(as_uuid=True)),
    Column("rule_version", Integer),
    Column("source", Text),
    Column("mode", Text),
    Column("status", Text),
    Column("flow_run_id", UUID(as_uuid=True)),
    Column("updated_at", DateTime(timezone=True)),
    Column("start_date", Date),
    Column("end_date", Date),
    Column("definition", JSONB),
    schema="ops",
)
