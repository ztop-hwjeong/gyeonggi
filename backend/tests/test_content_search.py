import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import MetaData, Table, insert
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from domain.collection.models import ArticleQuery, MaterialQuery
from domain.collection.reporting import CollectionReporting


@pytest.mark.skipif(not os.environ.get("COLLECTION_TEST_DATABASE_URL"), reason="전용 검증 DB 필요")
def test_news_body_only_query_is_shared_by_news_and_material_lists():
    async def check() -> None:
        engine = create_async_engine(
            os.environ["COLLECTION_TEST_DATABASE_URL"], hide_parameters=True
        )
        marker = f"본문전용_{uuid4().hex}%"
        source_ids = (f"body-search-{uuid4().hex}", f"body-search-{uuid4().hex}")
        run_id = uuid4()
        try:
            async with engine.connect() as connection, connection.begin():
                metadata = MetaData()
                news = await connection.run_sync(
                    lambda sync: Table("news_items", metadata, schema="dw", autoload_with=sync)
                )
                search = await connection.run_sync(
                    lambda sync: Table("search_items", metadata, schema="dw", autoload_with=sync)
                )
                runs = await connection.run_sync(
                    lambda sync: Table(
                        "article_detail_runs", metadata, schema="ops", autoload_with=sync
                    )
                )
                responses = await connection.run_sync(
                    lambda sync: Table(
                        "article_responses", metadata, schema="st", autoload_with=sync
                    )
                )
                results = await connection.run_sync(
                    lambda sync: Table(
                        "article_detail_results", metadata, schema="st", autoload_with=sync
                    )
                )
                contents = await connection.run_sync(
                    lambda sync: Table(
                        "article_contents", metadata, schema="dw", autoload_with=sync
                    )
                )
                async with AsyncSession(
                    bind=connection, join_transaction_mode="create_savepoint"
                ) as session:
                    await session.execute(insert(runs).values(id=run_id, summary={}))
                    for source_id, body_marker in zip(
                        source_ids,
                        (marker, marker.replace("_", "x").replace("%", "x")),
                        strict=True,
                    ):
                        seed = {
                            "source": "bigkinds",
                            "source_id": source_id,
                            "title": "본문 없는 제목",
                            "summary": "본문 없는 요약",
                            "original_url": f"https://example.test/{source_id}",
                        }
                        await session.execute(
                            insert(news).values(source="bigkinds", source_id=source_id, data=seed)
                        )
                        await session.execute(
                            insert(responses).values(
                                id=uuid4(),
                                run_id=run_id,
                                source_id=source_id,
                                stage="curl_cffi",
                                seed=seed,
                                metadata={},
                                raw_object={"bucket": "tests", "key": source_id},
                            )
                        )
                        await session.execute(
                            insert(results).values(
                                run_id=run_id,
                                source_id=source_id,
                                result={"seed": seed, "status": "collected"},
                            )
                        )
                        await session.execute(
                            insert(contents).values(
                                source="bigkinds",
                                source_id=source_id,
                                content_hash=source_id,
                                title="본문 없는 제목",
                                body=(f"검증된 기사 본문 {body_marker} " * 30).strip(),
                                stage="curl_cffi",
                                run_id=run_id,
                                provenance={},
                            )
                        )
                    await session.execute(
                        insert(search).values(
                            provider="naver",
                            channel="blog",
                            source_id=f"blog-{source_ids[0]}",
                            content_hash=source_ids[0],
                            data={
                                "title": "블로그 제목",
                                "summary": "블로그 요약",
                                "url": f"https://blog.example/{source_ids[0]}",
                            },
                        )
                    )
                    reporting = CollectionReporting(session)
                    news = await reporting.articles(ArticleQuery(q=marker))
                    materials = await reporting.materials(MaterialQuery(q=marker))
                    posts = await reporting.materials(MaterialQuery(group="posts", q=marker))
                    assert news.total == len(news.items) == 1
                    assert materials.total == len(materials.items) == 1
                    assert news.items[0].id == materials.items[0].id
                    assert materials.items[0].kind == "news"
                    assert posts.total == 0
        finally:
            await engine.dispose()

    asyncio.run(check())
