from sqlalchemy import BigInteger, Column, DateTime, Integer, MetaData, String, Table
from sqlalchemy.dialects.postgresql import UUID

metadata = MetaData()

events = Table(
    "events",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("name", String),
    Column("occurred_at", DateTime(timezone=True)),
    Column("version", Integer),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
    schema="ops",
)

event_targets = Table(
    "event_targets",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("event_id", UUID(as_uuid=True)),
    Column("tag_id", String),
    Column("folder_id", UUID(as_uuid=True)),
    schema="ops",
)
