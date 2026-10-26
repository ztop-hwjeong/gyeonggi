import asyncio
import json
import os
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from domain.collection.errors import CollectionConflictError, CollectionNotFoundError
from domain.collection.models import (
    ArticleQuery,
    RequestQuery,
    RequestReview,
    RuleDefinition,
    RuleQuery,
    RuleUpdate,
    RunCreate,
)
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
                    with pytest.raises(CollectionConflictError):
                        await repository.review(key, RequestReview(reviewed=True))
                    assert (
                        await repository.requests(RequestQuery(rule_id=rule.id, status="active"))
                    ).total == 1
                    assert (
                        await repository.requests(RequestQuery(rule_id=rule.id, status="attention"))
                    ).total == 0
                    assert (
                        await repository.requests(
                            RequestQuery(rule_id=rule.id, source="naver_blog")
                        )
                    ).total == 0
                    assert (
                        await repository.requests(RequestQuery(rule_id=rule.id, mode="preview"))
                    ).total == 0
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
                    assert (
                        await repository.requests(RequestQuery(rule_id=rule.id, status="active"))
                    ).total == 0
                    assert (
                        await repository.requests(RequestQuery(rule_id=rule.id, status="cancelled"))
                    ).items[0].id == key
                    await session.execute(
                        text(
                            "UPDATE ops.collection_requests SET status='partial',"
                            "created_at=now()-interval '2 days' WHERE id=:id"
                        ),
                        {"id": key},
                    )
                    await session.commit()
                    partial = await repository.requests(
                        RequestQuery(
                            rule_id=rule.id, status="attention", source="bigkinds", mode="backfill"
                        )
                    )
                    assert partial.total == 1 and partial.items[0].id == key
                    reviewed = await repository.review(key, RequestReview(reviewed=True))
                    assert reviewed.reviewed_at is not None
                    assert (
                        await repository.requests(RequestQuery(rule_id=rule.id, status="attention"))
                    ).total == 0
                    assert (
                        await repository.requests(RequestQuery(rule_id=rule.id, status="partial"))
                    ).total == 1
                    await repository.review(key, RequestReview(reviewed=False))
                    assert (
                        await repository.requests(RequestQuery(rule_id=rule.id, status="attention"))
                    ).total == 1
                    assert (
                        await repository.requests(
                            RequestQuery(rule_id=rule.id, status="attention", offset=1)
                        )
                    ).items == []
                    matches = await repository.rules(RuleQuery(q="새로운 키워드", enabled=False))
                    assert any(item.id == rule.id for item in matches.items)
                    assert not any(
                        item.id == rule.id
                        for item in (
                            await repository.rules(RuleQuery(q="새로운 키워드", enabled=True))
                        ).items
                    )
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
                    assert before.partial_requests >= 1
                    assert len(after.daily_counts) == 7
                    results = await reporting.articles(ArticleQuery(source="bigkinds", q="100%"))
                    assert any(
                        source.source_id == article_id
                        for item in results.items
                        for source in item.sources
                    )
                    assert all(
                        "100%" in item.title or "100%" in item.summary for item in results.items
                    )
                    identity = next(
                        item.id
                        for item in results.items
                        if any(source.source_id == article_id for source in item.sources)
                    )
                    assert (await reporting.article(identity)).body is None
                    with pytest.raises(CollectionNotFoundError):
                        await reporting.article(uuid4())
                    detail_run = uuid4()
                    await session.execute(
                        text("INSERT INTO ops.article_detail_runs(id,summary) VALUES (:id,'{}')"),
                        {"id": detail_run},
                    )
                    for content_hash, body in [("old", "이전 본문"), ("new", "최신 본문")]:
                        await session.execute(
                            text(
                                "INSERT INTO dw.article_contents(source,source_id,content_hash,"
                                "title,body,stage,run_id,provenance) VALUES "
                                "('bigkinds',:id,:hash,'본문 제목',:body,'http',:run,'{}')"
                            ),
                            {
                                "id": article_id,
                                "hash": content_hash,
                                "body": body,
                                "run": detail_run,
                            },
                        )
                    detail = await reporting.article(identity)
                    assert detail.has_body and detail.body == "최신 본문"
                await connection.rollback()
        finally:
            await engine.dispose()

    asyncio.run(check())
