from sqlalchemy import Column, Integer, MetaData, Table, Text
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

publishers = Table(
    "publishers",
    metadata,
    Column("code", Text, primary_key=True),
    Column("name", Text),
    Column("category_code", Text),
    Column("category_source", Text),
    schema="dw",
)
categories = Table(
    "publisher_categories",
    metadata,
    Column("code", Text, primary_key=True),
    Column("name", Text),
    Column("sort_order", Integer),
    schema="dw",
)
domains = Table(
    "publisher_domains",
    metadata,
    Column("domain", Text, primary_key=True),
    Column("publisher_code", Text),
    Column("evidence", JSONB),
    schema="dw",
)
source_categories = Table(
    "publisher_source_categories",
    metadata,
    Column("source", Text, primary_key=True),
    Column("source_category_code", Text, primary_key=True),
    Column("name", Text),
    Column("sort_order", Integer),
    schema="dw",
)
source_codes = Table(
    "publisher_source_codes",
    metadata,
    Column("source", Text, primary_key=True),
    Column("source_code", Text, primary_key=True),
    Column("publisher_code", Text),
    Column("source_name", Text),
    Column("source_category_code", Text),
    Column("source_data", JSONB),
    schema="dw",
)
