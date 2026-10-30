import asyncio
import os
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import Column, MetaData, String, Table, func, insert, select, update
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from domain.analysis_reports.models import (
    RelevanceRequest,
    ReportBulkDecision,
    ReportCreate,
    ReportDecisionWrite,
    ReportUpdate,
)
from domain.analysis_reports.repository import (
    AnalysisReportConflict,
    AnalysisReportInvalid,
    AnalysisReportNotFound,
    AnalysisReportRepository,
)
from domain.analysis_reports.tables import (
    analysis_report_decision_history,
    analysis_report_decisions,
    report_relevance_runs,
)
from domain.article_workflow.models import TargetWrite
from domain.article_workflow.repository import ArticleWorkflow
from domain.article_workflow.tables import article_target_links
from domain.collection.models import RuleDefinition, RuleTargets, RuleUpdate
from domain.collection.repository import CollectionRepository
from domain.collection.tables import article_contents, article_detail_runs, articles, material_keys


def test_report_criteria_rejects_null_before_database_access(client):
    response = client.put(
        f"/analysis-reports/{uuid4()}", json={"version": 1, "relevance_criteria": None}
    )
    assert response.status_code == 422


@pytest.mark.skipif(
    not os.environ.get("ANALYSIS_TEST_DATABASE_URL"), reason="PostgreSQL 통합 검증 주소 필요"
)
def test_report_workspace_uses_live_terms_and_isolates_decisions():
    async def check():
        engine = create_async_engine(os.environ["ANALYSIS_TEST_DATABASE_URL"], hide_parameters=True)
        try:
            async with engine.connect() as connection, connection.begin():
                session = AsyncSession(bind=connection, join_transaction_mode="create_savepoint")
                async with session:
                    workflow = ArticleWorkflow(session)
                    collections = CollectionRepository(session)
                    reports = AnalysisReportRepository(session)
                    target = await workflow.save_target(
                        TargetWrite(kind="current_issue", name="현안", description="현안 설명")
                    )
                    default = (await reports.list(target_id=target.id))[0]
                    assert default.is_default and default.description == "현안 설명"
                    await session.commit()
                    rule = await collections.save_rule(
                        RuleDefinition(name="키워드", terms=("%특수_문자",), sources=("bigkinds",))
                    )
                    await collections.save_rule_targets(
                        rule.id, RuleTargets(target_ids=[target.id])
                    )
                    assert (await reports.get(default.id)).keyword_terms == ["%특수_문자"]
                    await session.commit()
                    manual = await reports.update(
                        default.id,
                        ReportUpdate(version=default.version, keyword_terms=["수동 키워드"]),
                    )
                    await collections.save_rule(
                        RuleUpdate(
                            **{
                                **rule.definition.model_dump(),
                                "terms": ("%특수_문자", "추가 키워드"),
                                "version": rule.version,
                            }
                        ),
                        rule.id,
                    )
                    assert (await reports.get(default.id)).keyword_terms == ["수동 키워드"]
                    restored = await reports.update(
                        default.id, ReportUpdate(version=manual.version, keywords_automatic=True)
                    )
                    assert restored.keywords_automatic
                    assert restored.keyword_terms == ["%특수_문자", "추가 키워드"]

                    article_id = uuid4()
                    await session.execute(insert(material_keys).values(id=article_id, kind="news"))
                    await session.execute(
                        insert(articles).values(
                            id=article_id,
                            title="제목",
                            summary="검색 스니펫 %특수_문자",
                        )
                    )
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
                    page = await reports.articles(default.id, "all", "all", None, 0, 20)
                    assert page.total == 1 and page.matched == 0 and page.unmatched == 1
                    second = await reports.create(
                        ReportCreate(target_id=target.id, title="별도 보고서")
                    )
                    await reports.decide(
                        default.id,
                        article_id,
                        ReportDecisionWrite(decision="exclude", reason="보고서별 제외"),
                    )
                    assert (
                        await reports.articles(default.id, "all", "excluded", None, 0, 20)
                    ).total == 1
                    assert (
                        await reports.articles(second.id, "all", "included", None, 0, 20)
                    ).total == 1
                await connection.rollback()
        finally:
            await engine.dispose()

    asyncio.run(check())


@pytest.mark.skipif(
    not os.environ.get("ANALYSIS_TEST_DATABASE_URL"), reason="PostgreSQL 통합 검증 주소 필요"
)
def test_report_filters_latest_original_body_and_literal_keywords():
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
        marker = uuid4().hex
        try:
            async with engine.connect() as connection, connection.begin():
                async with AsyncSession(
                    bind=connection, join_transaction_mode="create_savepoint"
                ) as session:
                    workflow = ArticleWorkflow(session)
                    target = await workflow.save_target(
                        TargetWrite(kind="current_issue", name=marker)
                    )
                    reports = AnalysisReportRepository(session)
                    report = await reports.create(
                        ReportCreate(
                            target_id=target.id,
                            keywords_automatic=False,
                            keyword_terms=["자립학교", "100%", "A_B"],
                        )
                    )
                    article_id = await session.scalar(
                        insert(news)
                        .values(
                            source="bigkinds",
                            source_id=marker,
                            data={
                                "title": "학교 운영 안내",
                                "summary": "자립학교",
                                "original_url": f"https://report.example/{marker}",
                            },
                        )
                        .returning(news.c.article_id)
                    )
                    assert article_id is not None
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
                    now = datetime.now(UTC)
                    for index, body in enumerate(
                        ("자립학교 과거 본문", "100명과 A1B 대상 안내", "100% 지원과 A_B 운영")
                    ):
                        run_id = uuid4()
                        await session.execute(
                            insert(article_detail_runs).values(id=run_id, summary={})
                        )
                        saved_id = await session.scalar(
                            insert(article_contents)
                            .values(
                                source="bigkinds",
                                source_id=marker,
                                title="학교 운영 안내",
                                content_hash=sha256(body.encode()).hexdigest(),
                                body=body,
                                stage="http",
                                run_id=run_id,
                                provenance={},
                                created_at=now + timedelta(seconds=index),
                            )
                            .returning(article_contents.c.article_id)
                        )
                        assert saved_id == article_id
                        if index == 1:
                            unmatched = await reports.articles(
                                report.id, "unmatched", "all", None, 0, 1
                            )
                            assert (
                                unmatched.total,
                                unmatched.matched,
                                unmatched.filtered_total,
                            ) == (1, 0, 1)
                            assert unmatched.items[0].content_preview == body
                        if index == 2:
                            matched = await reports.articles(
                                report.id, "matched", "all", None, 0, 1
                            )
                            assert (
                                matched.total,
                                matched.matched,
                                matched.unmatched,
                                matched.filtered_total,
                            ) == (1, 1, 0, 1)
                            assert matched.items[0].matched_keywords == ["100%", "A_B"]
                            empty_page = await reports.articles(
                                report.id, "matched", "all", None, 1, 1
                            )
                            assert empty_page.filtered_total == 1 and empty_page.items == []
                    await session.commit()
                    other = await reports.create(
                        ReportCreate(target_id=target.id, title="다른 보고서")
                    )
                    await reports.decide(
                        report.id,
                        article_id,
                        ReportDecisionWrite(decision="exclude", reason="검토 제외"),
                    )
                    assert (
                        await reports.articles(report.id, "all", "included", None, 0, 20)
                    ).filtered_total == 0
                    assert (
                        await reports.articles(other.id, "all", "unreviewed", None, 0, 20)
                    ).filtered_total == 1
                    await reports.decide(
                        report.id, article_id, ReportDecisionWrite(decision="release")
                    )
                    assert (
                        await reports.articles(report.id, "all", "unreviewed", None, 0, 20)
                    ).filtered_total == 1
                    from domain.analysis_reports.tables import analysis_report_decision_history

                    history = list(
                        await session.scalars(
                            select(analysis_report_decision_history.c.action)
                            .where(
                                analysis_report_decision_history.c.report_id == report.id,
                            )
                            .order_by(analysis_report_decision_history.c.id)
                        )
                    )
                    assert history == ["exclude", "release"]
                await connection.rollback()
        finally:
            await engine.dispose()

    asyncio.run(check())


@pytest.mark.skipif(
    not os.environ.get("ANALYSIS_TEST_DATABASE_URL"), reason="PostgreSQL 통합 검증 주소 필요"
)
def test_bulk_report_decision_is_atomic():
    async def check():
        engine = create_async_engine(os.environ["ANALYSIS_TEST_DATABASE_URL"], hide_parameters=True)
        try:
            async with engine.connect() as connection, connection.begin():
                async with AsyncSession(
                    bind=connection, join_transaction_mode="create_savepoint"
                ) as session:
                    workflow = ArticleWorkflow(session)
                    reports = AnalysisReportRepository(session)
                    target = await workflow.save_target(
                        TargetWrite(kind="current_issue", name="일괄")
                    )
                    other = await workflow.save_target(
                        TargetWrite(kind="current_issue", name="외부")
                    )
                    report = await reports.create(ReportCreate(target_id=target.id))
                    valid_ids = [uuid4(), uuid4()]
                    outsider = uuid4()
                    for article_id in [*valid_ids, outsider]:
                        await session.execute(
                            insert(material_keys).values(id=article_id, kind="news")
                        )
                        await session.execute(
                            insert(articles).values(id=article_id, title=str(article_id))
                        )
                    for article_id, target_id in [
                        *[(item, target.id) for item in valid_ids],
                        (outsider, other.id),
                    ]:
                        await session.execute(
                            insert(article_target_links).values(
                                article_id=article_id,
                                target_id=target_id,
                                decision="include",
                                origin="manual",
                                reason="검증",
                                matched_terms=[],
                            )
                        )
                    with pytest.raises(AnalysisReportInvalid):
                        await reports.decide_bulk(
                            report.id,
                            ReportBulkDecision(
                                article_ids=[valid_ids[0], outsider],
                                decision="exclude",
                                reason="일괄 제외",
                            ),
                        )
                    assert (
                        await session.scalar(
                            select(func.count())
                            .select_from(analysis_report_decisions)
                            .where(analysis_report_decisions.c.report_id == report.id)
                        )
                        == 0
                    )
                    assert (
                        await session.scalar(
                            select(func.count())
                            .select_from(analysis_report_decision_history)
                            .where(analysis_report_decision_history.c.report_id == report.id)
                        )
                        == 0
                    )
                    await reports.decide_bulk(
                        report.id,
                        ReportBulkDecision(
                            article_ids=valid_ids, decision="exclude", reason="일괄 제외"
                        ),
                    )
                    assert (
                        await session.scalar(
                            select(func.count())
                            .select_from(analysis_report_decisions)
                            .where(analysis_report_decisions.c.report_id == report.id)
                        )
                        == 2
                    )
                    assert (
                        await session.scalar(
                            select(func.count())
                            .select_from(analysis_report_decision_history)
                            .where(analysis_report_decision_history.c.report_id == report.id)
                        )
                        == 2
                    )
                await connection.rollback()
        finally:
            await engine.dispose()

    asyncio.run(check())


@pytest.mark.skipif(
    not os.environ.get("ANALYSIS_TEST_DATABASE_URL"), reason="PostgreSQL 통합 검증 주소 필요"
)
def test_relevance_status_preview_queue_and_detail():
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
        marker = uuid4().hex
        try:
            async with engine.connect() as connection, connection.begin():
                async with AsyncSession(
                    bind=connection, join_transaction_mode="create_savepoint"
                ) as session:
                    workflow = ArticleWorkflow(session)
                    reports = AnalysisReportRepository(session)
                    target = await workflow.save_target(
                        TargetWrite(kind="current_issue", name="AI 현안")
                    )
                    report = await reports.create(ReportCreate(target_id=target.id))
                    report = await reports.update(
                        report.id,
                        ReportUpdate(version=report.version, relevance_criteria="학교 정책 관련성"),
                    )
                    article_id = await session.scalar(
                        insert(news)
                        .values(
                            source="bigkinds",
                            source_id=marker,
                            data={
                                "title": "학교 정책 기사",
                                "summary": "summary-only",
                                "original_url": f"https://ai.example/{marker}",
                            },
                        )
                        .returning(news.c.article_id)
                    )
                    assert article_id is not None
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
                    run_id = uuid4()
                    await session.execute(insert(article_detail_runs).values(id=run_id, summary={}))
                    body = "학교 정책의 실제 원문"
                    content = await session.execute(
                        insert(article_contents)
                        .values(
                            source="bigkinds",
                            source_id=marker,
                            title="학교 정책 기사",
                            content_hash=sha256(body.encode()).hexdigest(),
                            body=body,
                            stage="http",
                            run_id=run_id,
                            provenance={},
                        )
                        .returning(
                            article_contents.c.id,
                            article_contents.c.article_id,
                            article_contents.c.content_hash,
                        )
                    )
                    content_id, saved_id, content_hash = content.one()
                    assert saved_id == article_id
                    criteria_hash = sha256(report.relevance_criteria.encode()).hexdigest()
                    await session.execute(
                        insert(report_relevance_runs).values(
                            id=uuid4(),
                            batch_id=uuid4(),
                            report_id=report.id,
                            article_id=article_id,
                            content_id=content_id,
                            content_hash=content_hash,
                            title="학교 정책 기사",
                            criteria=report.relevance_criteria,
                            criteria_hash=criteria_hash,
                            model="gpt-6-luna",
                            status="completed",
                            relevance="related",
                            reason="직접 관련",
                            evidence=["실제 원문"],
                            usage={},
                            created_at=datetime.now(UTC) - timedelta(seconds=1),
                        )
                    )
                    summary_only = await reports.articles(
                        report.id, "all", "all", "summary-only", 0, 20
                    )
                    summary_preview = await reports.preview_relevance(
                        report.id, RelevanceRequest(scope="filtered", q="summary-only")
                    )
                    assert summary_only.filtered_total == 0 and summary_preview.eligible == 0
                    related = await reports.articles(
                        report.id, "all", "all", None, 0, 20, "related"
                    )
                    assert (
                        related.filtered_total == 1
                        and related.ai_related == 1
                        and related.ai_unjudged == 0
                    )
                    preview = await reports.preview_relevance(
                        report.id,
                        RelevanceRequest(
                            scope="filtered",
                            mode="unjudged",
                            keyword_match="all",
                            inclusion="all",
                            ai_relevance="all",
                        ),
                    )
                    assert preview.eligible == 0
                    detail = await reports.article_detail(report.id, article_id)
                    assert detail.ai_reason == "직접 관련" and detail.ai_evidence == ["실제 원문"]
                    changed = await reports.update(
                        report.id,
                        ReportUpdate(version=report.version, relevance_criteria="변경된 기준"),
                    )
                    outdated = await reports.articles(
                        changed.id, "all", "all", None, 0, 20, "outdated"
                    )
                    assert outdated.filtered_total == 1 and outdated.ai_outdated == 1
                    preview = await reports.preview_relevance(
                        changed.id,
                        RelevanceRequest(
                            scope="filtered",
                            mode="unjudged",
                            keyword_match="all",
                            inclusion="all",
                            ai_relevance="all",
                        ),
                    )
                    assert preview.eligible == 1
                    queued = await reports.enqueue_relevance(
                        changed.id,
                        RelevanceRequest(scope="filtered", preview_fingerprint=preview.fingerprint),
                    )
                    assert queued.queued == 1
                    with pytest.raises(AnalysisReportConflict):
                        await reports.enqueue_relevance(
                            changed.id,
                            RelevanceRequest(
                                scope="filtered", preview_fingerprint=preview.fingerprint
                            ),
                        )
                    fresh = await reports.preview_relevance(
                        changed.id, RelevanceRequest(scope="filtered")
                    )
                    assert fresh.eligible == 0 and fresh.pending == 1
                    other = await reports.create(
                        ReportCreate(target_id=target.id, title="유지할 보고서")
                    )
                    await reports.decide(
                        other.id, article_id, ReportDecisionWrite(decision="include")
                    )
                    await reports.decide(
                        changed.id,
                        article_id,
                        ReportDecisionWrite(decision="exclude", reason="삭제 검증"),
                    )
                    with pytest.raises(AnalysisReportConflict):
                        await reports.delete(changed.id, changed.version + 1)
                    await session.execute(
                        update(report_relevance_runs)
                        .where(report_relevance_runs.c.batch_id == queued.batch_id)
                        .values(status="running")
                    )
                    with pytest.raises(AnalysisReportConflict, match="진행 중"):
                        await reports.delete(changed.id, changed.version)
                    assert (await reports.get(changed.id)).id == changed.id
                    await session.execute(
                        update(report_relevance_runs)
                        .where(report_relevance_runs.c.batch_id == queued.batch_id)
                        .values(status="submitted")
                    )
                    await reports.delete(changed.id, changed.version)
                    with pytest.raises(AnalysisReportNotFound):
                        await reports.get(changed.id)
                    for table in (
                        analysis_report_decisions,
                        analysis_report_decision_history,
                        report_relevance_runs,
                    ):
                        assert (
                            await session.scalar(
                                select(func.count())
                                .select_from(table)
                                .where(table.c.report_id == changed.id)
                            )
                            == 0
                        )
                    assert (
                        await session.scalar(
                            select(articles.c.id).where(articles.c.id == article_id)
                        )
                        == article_id
                    )
                    assert (
                        await session.scalar(
                            select(article_contents.c.body).where(
                                article_contents.c.id == content_id
                            )
                        )
                        == body
                    )
                    assert (await reports.get(other.id)).title == "유지할 보고서"
                    assert (
                        await reports.articles(other.id, "all", "included", None, 0, 20)
                    ).filtered_total == 1
                    default = next(
                        item for item in await reports.list(target_id=target.id) if item.is_default
                    )
                    await reports.delete(default.id, default.version)
                    assert [item.id for item in await reports.list(target_id=target.id)] == [
                        other.id
                    ]
                    assert (
                        await reports.create(ReportCreate(target_id=target.id))
                    ).target_id == target.id
                await connection.rollback()
        finally:
            await engine.dispose()

    asyncio.run(check())
