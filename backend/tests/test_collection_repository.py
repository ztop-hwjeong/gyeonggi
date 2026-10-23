import asyncio
import json
import os
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from domain.collection.errors import CollectionConflictError
from domain.collection.models import ArticleQuery, RuleDefinition, RuleUpdate, RunCreate
from domain.collection.reporting import CollectionReporting
from domain.collection.repository import CollectionRepository


@pytest.mark.skipif(
    not os.environ.get("COLLECTION_TEST_DATABASE_URL"), reason="PostgreSQL 통합 검증 주소 필요"
)
def test_rule_versions_request_snapshot_idempotency_and_cancellation():
    async def check():
        engine = create_async_engine(
            os.environ["COLLECTION_TEST_DATABASE_URL"], hide_parameters=True
        )
        try:
            async with engine.connect() as connection, connection.begin():
                session = AsyncSession(bind=connection, join_transaction_mode="create_savepoint")
                async with session:
                    repository = CollectionRepository(session)
                    definition = RuleDefinition(
                        name="통합 검증", terms=("학교 정책",), sources=("bigkinds",)
                    )
                    rule = await repository.save_rule(definition)
                    body = RunCreate(
                        rule_id=rule.id,
                        version=1,
                        source="bigkinds",
                        mode="backfill",
                        start_date=date(2026, 6, 1),
                        end_date=date(2026, 10, 23),
                    )
                    key = uuid4()
                    queued = await repository.enqueue(key, body)
                    assert (await repository.enqueue(key, body)).id == queued.id
                    changed_body = body.model_copy(update={"mode": "incremental"})
                    with pytest.raises(CollectionConflictError):
                        await repository.enqueue(key, changed_body)
                    update = RuleUpdate(**definition.model_dump(), version=1)
                    update.terms = ("새로운 키워드",)
                    changed = await repository.save_rule(update, rule.id)
                    assert changed.version == 2
                    with pytest.raises(CollectionConflictError):
                        await repository.save_rule(update, rule.id)
                    assert len(await repository.versions(rule.id)) == 2
                    assert (await repository.request(key)).definition.terms == ("학교 정책",)
                    assert (await repository.enqueue(key, body)).id == key
                    with pytest.raises(CollectionConflictError):
                        await repository.enqueue(uuid4(), body)
                    assert (await repository.cancel(key)).status == "cancelled"
                    reporting = CollectionReporting(session)
                    before = await reporting.overview()
                    article_id = str(uuid4())
                    await session.execute(
                        text(
                            "INSERT INTO dw.news_items(source,source_id,data) "
                            "VALUES ('bigkinds',:id,CAST(:data AS jsonb))"
                        ),
                        {
                            "id": article_id,
                            "data": json.dumps(
                                {
                                    "source_id": article_id,
                                    "title": "통합 검증 100%",
                                    "summary": "검색 결과",
                                    "published_on": "2026-10-23",
                                }
                            ),
                        },
                    )
                    after = await reporting.overview()
                    assert after.total_items == before.total_items + 1
                    assert len(after.daily_counts) == 7
                    results = await reporting.articles(ArticleQuery(source="bigkinds", q="100%"))
                    assert any(item.source_id == article_id for item in results.items)
                    assert all(
                        "100%" in item.title or "100%" in item.summary for item in results.items
                    )
                await connection.rollback()
        finally:
            await engine.dispose()

    asyncio.run(check())
