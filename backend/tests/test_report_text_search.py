import asyncio
import os
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import Column, MetaData, String, Table, func, insert, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from domain.analysis_reports.models import RelevanceRequest, ReportCreate, ReportUpdate
from domain.analysis_reports.repository import AnalysisReportRepository
from domain.article_workflow.models import TargetWrite
from domain.article_workflow.repository import ArticleWorkflow
from domain.article_workflow.tables import article_target_links
from domain.collection.tables import article_contents, article_detail_runs


@pytest.mark.skipif(
    not os.environ.get("ANALYSIS_TEST_DATABASE_URL"), reason="PostgreSQL 통합 검증 주소 필요"
)
def test_literal_search_and_latest_body_remain_exact_with_trigram_indexes():
    async def check():
        engine = create_async_engine(os.environ["ANALYSIS_TEST_DATABASE_URL"], hide_parameters=True)
        news = Table(
            "news_items",
            MetaData(),
            Column("source", String),
            Column("source_id", String),
            Column("data", JSONB),
            Column("article_id", UUID(as_uuid=True)),
            schema="dw",
        )
        examples = [
            ("다른 제목", ["황현필 과거 본문", "학교 교육과 AI 안내 100% A_B C:\\수집"]),
            ("황현필 교육 AI", []),
            ("다른 제목", ["100명 A1B C:/수집 ai 학교 example.com"]),
            ("새 제목", ["경기도교육청 경기도 교육청"]),
            ("빈 본문 제목", []),
            ("다른 제목", ["황 현필"]),
        ]
        expected_cases = {
            "황현필": {1},
            "교육": {0, 1, 3},
            "AI": {0, 1, 2},
            "100%": {0},
            "A_B": {0},
            "C:\\수집": {0},
            "경기도 교육청": {3},
            "없는 검색어": set(),
            ".": {2},
            "%": {0},
            "_": {0},
            "\\": {0},
        }
        try:
            async with engine.connect() as connection, connection.begin():
                async with AsyncSession(
                    bind=connection, join_transaction_mode="create_savepoint"
                ) as session:
                    target = await ArticleWorkflow(session).save_target(
                        TargetWrite(kind="regular", name="검색 정확도 검증")
                    )
                    reports = AnalysisReportRepository(session)
                    report = await reports.create(
                        ReportCreate(
                            target_id=target.id, keywords_automatic=False, keyword_terms=[]
                        )
                    )
                    run_id = uuid4()
                    await session.execute(insert(article_detail_runs).values(id=run_id, summary={}))
                    ids = []
                    for title, bodies in examples:
                        marker = uuid4().hex
                        article_id = await session.scalar(
                            insert(news)
                            .values(
                                source="bigkinds",
                                source_id=marker,
                                data={
                                    "title": title,
                                    "summary": "없는 검색어는 요약에만 존재",
                                    "original_url": f"https://search.example/{marker}",
                                },
                            )
                            .returning(news.c.article_id)
                        )
                        ids.append(article_id)
                        await session.execute(
                            insert(article_target_links).values(
                                article_id=article_id,
                                target_id=target.id,
                                decision="include",
                                origin="manual",
                                reason="검증",
                                matched_terms=[],
                            )
                        )
                        for version, body in enumerate(bodies):
                            await session.execute(
                                insert(article_contents).values(
                                    source="bigkinds",
                                    source_id=marker,
                                    title=title,
                                    content_hash=sha256(body.encode()).hexdigest(),
                                    body=body,
                                    stage="http",
                                    run_id=run_id,
                                    provenance={},
                                    created_at=datetime.now(UTC) + timedelta(seconds=version),
                                )
                            )
                    await session.execute(select(func.set_config("jit", "off", True)))
                    for index_mode in ("on", "off"):
                        await session.execute(
                            select(func.set_config("enable_seqscan", index_mode, True))
                        )
                        for term, positions in expected_cases.items():
                            expected = {ids[position] for position in positions}
                            report = await reports.update(
                                report.id,
                                ReportUpdate(version=report.version, keyword_terms=[term]),
                            )
                            matched = await reports.articles(
                                report.id, "matched", "all", None, 0, 200
                            )
                            unmatched = await reports.articles(
                                report.id, "unmatched", "all", None, 0, 200
                            )
                            searched = await reports.articles(report.id, "all", "all", term, 0, 200)
                            assert {item.id for item in matched.items} == expected, term
                            assert all(item.is_keyword_match for item in matched.items)
                            assert {item.id for item in unmatched.items} == set(ids) - expected
                            assert {item.id for item in searched.items} == expected, term
                            preview = await reports.preview_relevance(
                                report.id, RelevanceRequest(scope="filtered", q=term)
                            )
                            assert preview.eligible == len(expected - {ids[1], ids[4]})
                            assert preview.skipped_no_body == len(expected & {ids[1], ids[4]})
                await connection.rollback()
        finally:
            await engine.dispose()

    asyncio.run(check())
