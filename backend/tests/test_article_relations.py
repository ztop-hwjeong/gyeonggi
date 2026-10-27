import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import Column, MetaData, String, Table, insert, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from domain.article_workflow.models import SentimentWrite
from domain.article_workflow.relations import ArticleRelations
from domain.article_workflow.tables import article_reprints, article_sentiment_history
from domain.collection.tables import article_contents, articles

metadata = MetaData()
news_items = Table(
    "news_items",
    metadata,
    Column("source", String),
    Column("source_id", String),
    Column("data", JSONB),
    schema="dw",
)
article_sources = Table(
    "article_sources",
    metadata,
    Column("article_id", article_contents.c.article_id.type),
    Column("source", String),
    Column("source_id", String),
    schema="dw",
)
detail_runs = Table(
    "article_detail_runs",
    metadata,
    Column("id", article_contents.c.article_id.type),
    Column("summary", JSONB),
    schema="ops",
)
stored_contents = Table(
    "article_contents",
    metadata,
    Column("source", String),
    Column("source_id", String),
    Column("content_hash", String),
    Column("title", String),
    Column("body", String),
    Column("stage", String),
    Column("run_id", article_contents.c.article_id.type),
    Column("provenance", JSONB),
    schema="dw",
)


@pytest.mark.skipif(
    not os.environ.get("ANALYSIS_TEST_DATABASE_URL"),
    reason="독립 PostgreSQL 테스트 데이터베이스 필요",
)
def test_sentiment_override_and_reprint_current_body_only():
    asyncio.run(_check_sentiment_override_and_reprint_current_body_only())


async def _check_sentiment_override_and_reprint_current_body_only():
    engine = create_async_engine(os.environ["ANALYSIS_TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    marker = uuid4().hex
    source_a, source_b = f"press-a-{marker}", f"press-b-{marker}"
    run_id = uuid4()
    try:
        async with factory() as session:
            async with session.begin():
                for source_id, publisher in ((source_a, "언론 A"), (source_b, "언론 B")):
                    await session.execute(
                        insert(news_items).values(
                            source="bigkinds",
                            source_id=source_id,
                            data={
                                "title": f"기사 {source_id}",
                                "publisher": publisher,
                                "original_url": f"https://example.test/{source_id}",
                            },
                        )
                    )
                await session.execute(insert(detail_runs).values(id=run_id, summary={}))
                ids = dict(
                    (
                        await session.execute(
                            select(article_sources.c.source_id, article_sources.c.article_id).where(
                                article_sources.c.source_id.in_((source_a, source_b))
                            )
                        )
                    ).all()
                )
                for source_id in (source_a, source_b):
                    await session.execute(
                        insert(stored_contents).values(
                            source="bigkinds",
                            source_id=source_id,
                            content_hash=f"hash-{source_id}",
                            title=source_id,
                            body=f"본문 {source_id}",
                            stage="publisher",
                            run_id=run_id,
                            provenance={},
                        )
                    )
                article_a, article_b = sorted(ids.values())
                source_for_a = next(k for k, v in ids.items() if v == article_a)
                source_for_b = next(k for k, v in ids.items() if v == article_b)
                await session.execute(
                    insert(article_reprints).values(
                        article_a_id=article_a,
                        article_b_id=article_b,
                        article_a_content_hash=f"hash-{source_for_a}",
                        article_b_content_hash=f"hash-{source_for_b}",
                        body_similarity=0.93,
                        matching_basis="본문 유사도",
                    )
                )
            relations = ArticleRelations(session)
            assert (await relations.sentiment(article_a)).sentiment is None
            result = await relations.override_sentiment(
                article_a,
                SentimentWrite(
                    sentiment="중립",
                    mixed_sentiment=True,
                    sentiment_reason="긍정과 부정 관점 병기",
                ),
            )
            assert result.origin == "manual"
            assert result.mixed_sentiment is True
            assert len(await relations.reprints(article_a)) == 1
            history = await session.scalar(
                select(article_sentiment_history.c.id).where(
                    article_sentiment_history.c.article_id == article_a
                )
            )
            assert history is not None
            await session.commit()
            async with session.begin():
                await session.execute(
                    insert(stored_contents).values(
                        source="bigkinds",
                        source_id=source_for_b,
                        content_hash=f"new-hash-{source_for_b}",
                        title=source_for_b,
                        body="변경된 본문",
                        stage="publisher",
                        run_id=run_id,
                        provenance={},
                    )
                )
            assert await relations.reprints(article_a) == []
            assert (
                await session.scalar(select(articles.c.id).where(articles.c.id == article_a))
            ) == article_a
    finally:
        await engine.dispose()
