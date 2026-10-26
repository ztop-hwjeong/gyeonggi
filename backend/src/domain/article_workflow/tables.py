from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, MetaData, String, Table
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData()

analysis_targets = Table(
    "analysis_targets",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("kind", String),
    Column("name", String),
    Column("description", String),
    Column("version", Integer),
    Column("archived_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
    schema="ops",
)

article_filter_rules = Table(
    "article_filter_rules",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("target_id", UUID(as_uuid=True)),
    Column("name", String),
    Column("priority", Integer),
    Column("decision", String),
    Column("conditions", JSONB),
    Column("enabled", Boolean),
    Column("version", Integer),
    Column("deleted_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
    schema="ops",
)

article_filter_rule_versions = Table(
    "article_filter_rule_versions",
    metadata,
    Column("rule_id", UUID(as_uuid=True), primary_key=True),
    Column("version", Integer, primary_key=True),
    Column("definition", JSONB),
    Column("created_at", DateTime(timezone=True)),
    schema="ops",
)

article_inclusions = Table(
    "article_inclusions",
    metadata,
    Column("article_id", UUID(as_uuid=True), primary_key=True),
    Column("decision", String),
    Column("origin", String),
    Column("reason", String),
    Column("matched_terms", JSONB),
    Column("rule_id", UUID(as_uuid=True)),
    Column("rule_version", Integer),
    Column("updated_at", DateTime(timezone=True)),
    schema="ops",
)

article_target_links = Table(
    "article_target_links",
    metadata,
    Column("article_id", UUID(as_uuid=True), primary_key=True),
    Column("target_id", UUID(as_uuid=True), primary_key=True),
    Column("decision", String),
    Column("origin", String),
    Column("reason", String),
    Column("matched_terms", JSONB),
    Column("rule_id", UUID(as_uuid=True)),
    Column("rule_version", Integer),
    Column("updated_at", DateTime(timezone=True)),
    schema="ops",
)

article_decision_history = Table(
    "article_decision_history",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("article_id", UUID(as_uuid=True)),
    Column("target_id", UUID(as_uuid=True)),
    Column("previous_decision", String),
    Column("decision", String),
    Column("action", String),
    Column("origin", String),
    Column("reason", String),
    Column("matched_terms", JSONB),
    Column("rule_id", UUID(as_uuid=True)),
    Column("rule_version", Integer),
    Column("created_at", DateTime(timezone=True)),
    schema="ops",
)
