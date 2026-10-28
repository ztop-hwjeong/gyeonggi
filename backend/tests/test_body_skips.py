import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import MetaData, Table, insert
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from domain.collection.models import ArticleQuery
from domain.collection.reporting import CollectionReporting
from domain.collection.tables import article_detail_results, article_detail_runs


@pytest.mark.skipif(not os.environ.get("COLLECTION_TEST_DATABASE_URL"), reason="전용 검증 DB 필요")
def test_latest_skip_is_deduplicated_and_valid_body_has_priority():
    async def check():
        engine = create_async_engine(
            os.environ["COLLECTION_TEST_DATABASE_URL"], hide_parameters=True
        )
        try:
            async with engine.connect() as connection, connection.begin():
                metadata = MetaData()
                news = await connection.run_sync(
                    lambda sync: Table("news_items", metadata, schema="dw", autoload_with=sync)
                )
                contents = await connection.run_sync(
                    lambda sync: Table(
                        "article_contents", metadata, schema="dw", autoload_with=sync
                    )
                )
                session = AsyncSession(bind=connection, join_transaction_mode="create_savepoint")
                async with session:
                    reporting = CollectionReporting(session)
                    before = (await reporting.overview()).body_skipped_articles
                    key = uuid4().hex
                    for source in ("bigkinds", "naver_news"):
                        await session.execute(
                            insert(news).values(
                                source=source,
                                source_id=f"{source}-{key}",
                                data={
                                    "title": f"영상 기사 {key}",
                                    "summary": "제목만 제공",
                                    "publisher": "언론사",
                                    "published_on": "2026-10-28",
                                    "original_url": f"https://news.example/{key}",
                                },
                            )
                        )
                    items = (await reporting.articles(ArticleQuery(q=key))).items
                    assert len(items) == 1 and len(items[0].sources) == 2
                    article_id = items[0].id
                    instant = datetime.now(UTC)
                    failed = uuid4()
                    await session.execute(
                        insert(article_detail_runs).values(
                            id=failed,
                            summary={"started_at": (instant - timedelta(minutes=1)).isoformat()},
                        )
                    )
                    await session.execute(
                        insert(article_detail_results).values(
                            run_id=failed,
                            source_id=f"bigkinds-{key}",
                            result={"seed": {"source": "bigkinds"}, "status": "failed"},
                        )
                    )
                    assert (await reporting.material(article_id)).body_skip_reason is None
                    skipped = uuid4()
                    await session.execute(
                        insert(article_detail_runs).values(
                            id=skipped, summary={"started_at": instant.isoformat()}
                        )
                    )
                    for source in ("bigkinds", "naver_news"):
                        await session.execute(
                            insert(article_detail_results).values(
                                run_id=skipped,
                                source_id=f"{source}-{key}",
                                result={
                                    "seed": {"source": source},
                                    "status": "skipped",
                                    "skip_reason": "no_text_body",
                                },
                            )
                        )
                    detail = await reporting.article(article_id)
                    assert detail.body_skip_reason == "no_text_body" and detail.body is None
                    assert (await reporting.material(article_id)).body_skip_reason == "no_text_body"
                    assert (await reporting.overview()).body_skipped_articles == before + 1
                    await session.execute(
                        insert(contents).values(
                            source="bigkinds",
                            source_id=f"bigkinds-{key}",
                            content_hash=key,
                            title="영상 기사",
                            body="다른 수집처에서 확인한 실제 본문",
                            stage="curl_cffi",
                            run_id=skipped,
                            provenance={},
                        )
                    )
                    detail = await reporting.article(article_id)
                    assert detail.has_body and detail.body_skip_reason is None
                    assert (await reporting.overview()).body_skipped_articles == before
        finally:
            await engine.dispose()

    asyncio.run(check())
