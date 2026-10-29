import asyncio
import os
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import Column, MetaData, String, Table, func, insert, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from domain.collection.models import MaterialQuery
from domain.collection.reporting import CollectionReporting
from domain.collection.tables import blog_contents, blog_posts


@pytest.mark.skipif(
    not os.environ.get("COLLECTION_TEST_DATABASE_URL"), reason="PostgreSQL 통합 검증 주소 필요"
)
def test_blog_body_detail_and_search_remain_blog_scoped():
    async def check():
        engine = create_async_engine(
            os.environ["COLLECTION_TEST_DATABASE_URL"], hide_parameters=True
        )
        meta = MetaData()
        keys = Table(
            "material_keys",
            meta,
            Column("id", UUID(as_uuid=True), primary_key=True),
            Column("kind", String),
            schema="dw",
        )
        sources = Table(
            "blog_sources",
            meta,
            Column("blog_post_id", UUID(as_uuid=True)),
            Column("source", String),
            Column("source_id", String),
            Column("url", String),
            schema="dw",
        )
        runs = Table(
            "blog_detail_runs",
            meta,
            Column("id", UUID(as_uuid=True), primary_key=True),
            Column("summary", JSONB),
            schema="ops",
        )
        try:
            async with engine.connect() as connection, connection.begin():
                session = AsyncSession(bind=connection, join_transaction_mode="create_savepoint")
                async with session:
                    post_id = await session.scalar(select(func.uuidv7()))
                    run_id = uuid4()
                    source_id = str(uuid4())
                    marker = f"블로그본문검색{source_id}ABCD"
                    await session.execute(insert(keys).values(id=post_id, kind="blog"))
                    await session.execute(
                        insert(blog_posts).values(
                            id=post_id,
                            title="목록 제목",
                            summary="목록 요약",
                            blog_name="검증 블로그",
                            published_on=date(2026, 10, 21),
                        )
                    )
                    await session.execute(
                        insert(sources).values(
                            blog_post_id=post_id,
                            source="naver_blog",
                            source_id=source_id,
                            url="https://blog.naver.com/example/1",
                        )
                    )
                    await session.execute(insert(runs).values(id=run_id, summary={}))
                    await session.execute(
                        insert(blog_contents).values(
                            blog_post_id=post_id,
                            source="naver_blog",
                            source_id=source_id,
                            content_hash="test-" + source_id,
                            title="본문 제목",
                            body=marker,
                            stage="html",
                            run_id=run_id,
                            provenance={},
                            original_published_on=date(2026, 10, 20),
                        )
                    )
                    reporting = CollectionReporting(session)
                    detail = await reporting.material(post_id)
                    assert detail.kind == "blog" and detail.has_body
                    assert detail.body == marker
                    assert detail.content_preview == marker
                    assert detail.original_published_on == date(2026, 10, 20)
                    assert detail.sentiment is None
                    blog_page = await reporting.materials(MaterialQuery(kind="blog", q=marker))
                    assert [item.id for item in blog_page.items] == [post_id]
                    for wildcard in ("%", "_"):
                        literal_query = marker[:-3] + wildcard + marker[-2:]
                        assert (
                            await reporting.materials(MaterialQuery(kind="blog", q=literal_query))
                        ).total == 0
                    news_page = await reporting.materials(MaterialQuery(kind="news", q=marker))
                    assert news_page.total == 0
                await connection.rollback()
        finally:
            await engine.dispose()

    asyncio.run(check())
