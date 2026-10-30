import asyncio
import os
import selectors
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import MetaData, Table, insert, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from relevance.repository import RelevanceRepository


@pytest.mark.skipif(
    not os.environ.get("ANALYSIS_TEST_DATABASE_URL"), reason="PostgreSQL 통합 검증 주소 필요"
)
@pytest.mark.parametrize("expired", [False, True])
def test_relevance_claim_preserves_snapshot_and_manual_decision(expired):
    async def check():
        url = make_url(os.environ["ANALYSIS_TEST_DATABASE_URL"]).set(
            drivername="postgresql+psycopg"
        )
        engine = create_async_engine(url, hide_parameters=True)
        try:
            async with engine.connect() as connection, connection.begin():
                metadata = MetaData()

                def reflect(sync):
                    return {
                        name: Table(
                            name, metadata, schema=schema, autoload_with=sync, resolve_fks=False
                        )
                        for schema, name in (
                            ("ops", "analysis_targets"),
                            ("ops", "analysis_reports"),
                            ("ops", "analysis_report_decisions"),
                            ("ops", "report_relevance_runs"),
                            ("dw", "news_items"),
                            ("dw", "article_contents"),
                            ("ops", "article_detail_runs"),
                        )
                    }

                tables = await connection.run_sync(reflect)
                marker = uuid4().hex
                target_id = await connection.scalar(
                    insert(tables["analysis_targets"])
                    .values(id=uuid4(), kind="current_issue", name=marker)
                    .returning(tables["analysis_targets"].c.id)
                )
                report_id = await connection.scalar(
                    select(tables["analysis_reports"].c.id).where(
                        tables["analysis_reports"].c.target_id == target_id
                    )
                )
                article_id = await connection.scalar(
                    insert(tables["news_items"])
                    .values(
                        source="bigkinds",
                        source_id=marker,
                        data={
                            "title": "Snapshot title",
                            "original_url": f"https://test.invalid/{marker}",
                        },
                    )
                    .returning(tables["news_items"].c.article_id)
                )
                content_ids = []
                for index, body in enumerate(("original exact evidence", "new replacement body")):
                    detail_id = uuid4()
                    await connection.execute(
                        insert(tables["article_detail_runs"]).values(id=detail_id, summary={})
                    )
                    content_ids.append(
                        await connection.scalar(
                            insert(tables["article_contents"])
                            .values(
                                source="bigkinds",
                                source_id=marker,
                                title="Snapshot title",
                                content_hash=sha256(body.encode()).hexdigest(),
                                body=body,
                                stage="http",
                                run_id=detail_id,
                                provenance={},
                                created_at=datetime.now(UTC) + timedelta(seconds=index),
                            )
                            .returning(tables["article_contents"].c.id)
                        )
                    )
                await connection.execute(
                    insert(tables["analysis_report_decisions"]).values(
                        report_id=report_id,
                        article_id=article_id,
                        decision="include",
                        reason="manual",
                    )
                )
                run_id = await connection.scalar(
                    insert(tables["report_relevance_runs"])
                    .values(
                        batch_id=uuid4(),
                        report_id=report_id,
                        article_id=article_id,
                        content_id=content_ids[0],
                        content_hash=sha256(b"original exact evidence").hexdigest(),
                        title="Snapshot title",
                        criteria="Keep original evidence",
                        criteria_hash=sha256(b"Keep original evidence").hexdigest(),
                        model="gpt-6-luna",
                        status="queued",
                    )
                    .returning(tables["report_relevance_runs"].c.id)
                )
                assert run_id is not None
                repository = RelevanceRepository(
                    async_sessionmaker(bind=connection, join_transaction_mode="create_savepoint")
                )
                item = await repository.claim(run_id, uuid4())
                assert item is not None and item.body == "original exact evidence"
                assert await repository.claim(run_id, uuid4()) is None
                row = (
                    (await connection.execute(select(tables["report_relevance_runs"])))
                    .mappings()
                    .one()
                )
                assert item.criteria in row["prompt"]
                assert sha256(row["prompt"].encode()).hexdigest() == row["prompt_hash"]
                if expired:
                    await connection.execute(
                        update(tables["report_relevance_runs"])
                        .where(tables["report_relevance_runs"].c.id == run_id)
                        .values(status="failed", error="lease_expired")
                    )
                    with pytest.raises(RuntimeError, match="소유권"):
                        await repository.complete(
                            item,
                            {
                                "relevance": "related",
                                "reason": "match",
                                "evidence": ["exact evidence"],
                            },
                            {},
                        )
                    await repository.fail(run_id, ValueError("late"))
                else:
                    await repository.complete(
                        item,
                        {"relevance": "related", "reason": "match", "evidence": ["exact evidence"]},
                        {"input_tokens": 10},
                    )
                row = (
                    (await connection.execute(select(tables["report_relevance_runs"])))
                    .mappings()
                    .one()
                )
                assert row["status"] == ("failed" if expired else "completed")
                if expired:
                    assert row["error"] == "lease_expired"
                decision = (
                    (await connection.execute(select(tables["analysis_report_decisions"])))
                    .mappings()
                    .one()
                )
                assert (decision["decision"], decision["reason"]) == ("include", "manual")
                await connection.rollback()
        finally:
            await engine.dispose()

    asyncio.run(check(), loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
