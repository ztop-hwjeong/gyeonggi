from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table
from sqlalchemy.dialects.postgresql import UUID

metadata = MetaData()

folders = Table(
    "tag_folders",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("parent_id", UUID(as_uuid=True)),
    Column("name", String),
    Column("version", Integer),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
    schema="ops",
)

folder_tags = Table(
    "folder_tags",
    metadata,
    Column("folder_id", UUID(as_uuid=True), primary_key=True),
    Column("tag_id", String, primary_key=True),
    Column("created_at", DateTime(timezone=True)),
    schema="ops",
)
