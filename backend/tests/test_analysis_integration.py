import asyncio
import os
from datetime import date
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from domain.analysis.application import AnalysisApplication, AnalysisApplyError
from domain.analysis.registry import TopicRegistry, TopicRegistryConflictError
from domain.analysis.registry_models import (
    ArticleTopicOverride,
    Topic,
    TopicEvidenceCreate,
    TopicMerge,
)
from domain.analysis.reporting import report_data
from domain.analysis.tables import topic_history, topics
from domain.article_workflow.repository import ArticleWorkflow
from domain.templates.catalog import TemplateCatalog
from domain.templates.rendering import TemplateRenderer


@pytest.mark.skipif(
    "ANALYSIS_TEST_DATABASE_URL" not in os.environ,
    reason="독립 PostgreSQL 테스트 데이터베이스 필요",
)
def test_saved_single_article_apply_override_and_report():
    catalog = TemplateCatalog(Path(__file__).resolve().parents[1] / "templates")

    async def check() -> None:
        engine = create_async_engine(os.environ["ANALYSIS_TEST_DATABASE_URL"])
        prefix = "t" + uuid4().hex[:12]
        source = "bigkinds"
        source_id = f"https://example.test/{prefix}/1"
        content_hash = "a" * 64
        topic_id = f"{prefix}-policy"
        run_id = uuid4()
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                registry = TopicRegistry(session)
                await registry.ensure_topics(
                    [Topic(id=topic_id, name=f"{prefix} 교육정책", description="정책 반응")]
                )
                async with session.begin():
                    detail_run_id = uuid4()
                    await session.execute(
                        text("INSERT INTO ops.article_detail_runs(id,summary) VALUES (:id,'{}')"),
                        {"id": detail_run_id},
                    )
                    await session.execute(
                        text(
                            "INSERT INTO dw.article_contents"
                            "(source,source_id,content_hash,title,body,stage,run_id,provenance) "
                            "VALUES (:source,:source_id,:hash,:title,:body,'http',:run_id,'{}')"
                        ),
                        {
                            "source": source,
                            "source_id": source_id,
                            "hash": content_hash,
                            "title": "경기도교육청 새 정책 발표",
                            "body": "경기도교육청 새 정책에 교사들이 환영했다.",
                            "run_id": detail_run_id,
                        },
                    )
                    await session.execute(
                        text(
                            "INSERT INTO ops.analysis_runs"
                            "(id,article_id,source,source_id,content_hash,model,"
                            "prompt,status,catalog_snapshot,model_draft) "
                            "VALUES (:id,(SELECT material_id FROM dw.material_sources "
                            "WHERE source=:source AND source_id=:source_id),"
                            ":source,:source_id,:hash,'gpt-6-luna','테스트 프롬프트','completed',"
                            "CAST(:catalog AS jsonb),CAST(:draft AS jsonb))"
                        ),
                        {
                            "id": run_id,
                            "source": source,
                            "source_id": source_id,
                            "hash": content_hash,
                            "catalog": f'{{"topics":[{{"id":"{topic_id}"}}]}}',
                            "draft": (
                                '{"article":{"topic_ids":["' + topic_id + '"],'
                                '"keywords":["정책"],"sentiment":"긍정",'
                                '"quote":"교사들이 환영했다","reason":"교사 환영",'
                                '"review_required":false},"topic_candidates":[]}'
                            ),
                        },
                    )
                application = AnalysisApplication(registry, ArticleWorkflow(session))
                applied = await application.apply(run_id)
                assert applied["topic_ids"] == [topic_id]
                assert (await registry.run(run_id)).applied_result == applied
                assert (await registry.runs_for_article(source, source_id))[0].id == run_id

                await registry.override_article_topic(
                    source, source_id, topic_id, ArticleTopicOverride(decision="exclude")
                )
                applied_again = await application.apply(run_id)
                assert applied_again["topic_ids"] == []
                data = await report_data(
                    registry, date(2026, 10, 26), [(await registry.run(run_id)).article_id]
                )
                assert data["articles"][0]["keywords"] == ""
                assert data["articles"][0]["title"] == "경기도교육청 새 정책 발표"
                content = TemplateRenderer(catalog).render("education-audit-press", "1.1.0", data)
                assert content.startswith(b"PK")

                bad_run = uuid4()
                async with session.begin():
                    await session.execute(
                        text(
                            "INSERT INTO ops.analysis_runs"
                            "(id,article_id,source,source_id,content_hash,model,"
                            "prompt,status,catalog_snapshot,model_draft) "
                            "SELECT :id,article_id,source,source_id,content_hash,model,"
                            "prompt,status,"
                            "catalog_snapshot,replace(model_draft::text,"
                            "'교사들이 환영했다','위조 인용')::jsonb "
                            "FROM ops.analysis_runs WHERE id=:original"
                        ),
                        {"id": bad_run, "original": run_id},
                    )
                with pytest.raises(AnalysisApplyError, match="인용"):
                    await AnalysisApplication(registry, ArticleWorkflow(session)).apply(bad_run)
                assert (await registry.run(bad_run)).applied_result is None
        finally:
            await engine.dispose()

    asyncio.run(check())


@pytest.mark.skipif(
    "ANALYSIS_TEST_DATABASE_URL" not in os.environ,
    reason="독립 PostgreSQL 테스트 데이터베이스 필요",
)
def test_candidate_promotion_backfills_prior_articles_and_preserves_override():
    async def check() -> None:
        engine = create_async_engine(os.environ["ANALYSIS_TEST_DATABASE_URL"])
        prefix = "t" + uuid4().hex[:12]
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                registry = TopicRegistry(session)
                results = []
                for index in (1, 2, 3):
                    results.append(
                        await registry.record(
                            TopicEvidenceCreate(
                                name=f"{prefix} 교권 쟁점",
                                description="교권 관련 보도",
                                source="bigkinds",
                                source_id=f"{prefix}-{index}",
                                publisher=f"언론사 {index}",
                                quote="교권 쟁점",
                            )
                        )
                    )
                assert [result.kind for result in results] == ["candidate", "candidate", "promoted"]
                topic_id = results[2].topic_id
                assert topic_id is not None
                for index in (1, 2, 3):
                    links = await registry.article_topics("bigkinds", f"{prefix}-{index}")
                    assert [(link.topic_id, link.origin) for link in links] == [(topic_id, "ai")]
                await registry.override_article_topic(
                    "bigkinds", f"{prefix}-1", topic_id, ArticleTopicOverride(decision="exclude")
                )
                await registry.record(
                    TopicEvidenceCreate(
                        name=f"{prefix} 교권 쟁점",
                        description="교권 관련 보도",
                        source="bigkinds",
                        source_id=f"{prefix}-1",
                        publisher="언론사 1",
                        quote="교권 쟁점",
                    )
                )
                assert (await registry.article_topics("bigkinds", f"{prefix}-1"))[0].origin == (
                    "manual_exclude"
                )
        finally:
            await engine.dispose()

    asyncio.run(check())


@pytest.mark.skipif(
    "ANALYSIS_TEST_DATABASE_URL" not in os.environ,
    reason="독립 PostgreSQL 테스트 데이터베이스 필요",
)
def test_merge_preserves_manual_decisions_and_rolls_back_conflict():
    async def check() -> None:
        engine = create_async_engine(os.environ["ANALYSIS_TEST_DATABASE_URL"])
        prefix = "t" + uuid4().hex[:12]
        ids = [f"{prefix}-{letter}" for letter in "abcdef"]
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                registry = TopicRegistry(session)
                await registry.ensure_topics(
                    [Topic(id=topic_id, name=topic_id, description="병합 검사") for topic_id in ids]
                )
                for old, target, decision, suffix in (
                    (ids[0], ids[1], "include", "included"),
                    (ids[2], ids[3], "exclude", "excluded"),
                ):
                    source_id = f"{prefix}-{suffix}"
                    async with session.begin():
                        await session.execute(
                            text(
                                "INSERT INTO dw.news_items(source,source_id,data) "
                                "VALUES ('bigkinds',:id,CAST(:data AS jsonb))"
                            ),
                            {"id": source_id, "data": '{"title":"병합 검사"}'},
                        )
                    await registry.sync_article_topics("bigkinds", source_id, [target])
                    await registry.override_article_topic(
                        "bigkinds",
                        source_id,
                        old,
                        ArticleTopicOverride(
                            decision=cast(Literal["include", "exclude"], decision)
                        ),
                    )
                    await registry.merge(old, TopicMerge(target_id=target))
                    links = await registry.article_topics("bigkinds", source_id)
                    assert [(link.topic_id, link.origin) for link in links] == [
                        (target, f"manual_{decision}")
                    ]
                conflict_id = f"{prefix}-conflict"
                await registry.override_article_topic(
                    "bigkinds", conflict_id, ids[4], ArticleTopicOverride(decision="include")
                )
                await registry.override_article_topic(
                    "bigkinds", conflict_id, ids[5], ArticleTopicOverride(decision="exclude")
                )
                before = await registry.article_topics("bigkinds", conflict_id)
                with pytest.raises(TopicRegistryConflictError):
                    await registry.merge(ids[4], TopicMerge(target_id=ids[5]))
                assert await registry.article_topics("bigkinds", conflict_id) == before
                assert {topic.id for topic in await registry.topics()} >= {ids[4], ids[5]}
        finally:
            await engine.dispose()

    asyncio.run(check())


@pytest.mark.skipif(
    "ANALYSIS_TEST_DATABASE_URL" not in os.environ,
    reason="독립 PostgreSQL 테스트 데이터베이스 필요",
)
def test_archive_hides_topic_and_preserves_history():
    async def check() -> None:
        engine = create_async_engine(os.environ["ANALYSIS_TEST_DATABASE_URL"])
        topic_id = "t" + uuid4().hex[:20]
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                registry = TopicRegistry(session)
                await registry.ensure_topics(
                    [Topic(id=topic_id, name=topic_id, description="보관 검증")]
                )
                await registry.archive(topic_id)
                assert all(topic.id != topic_id for topic in await registry.topics())
                result = await session.execute(
                    select(topics.c.archived_at).where(topics.c.id == topic_id)
                )
                assert result.scalar_one() is not None
                history = await session.execute(
                    select(topic_history.c.action)
                    .where(topic_history.c.topic_id == topic_id)
                    .order_by(topic_history.c.id.desc())
                    .limit(1)
                )
                assert history.scalar_one() == "archive"
        finally:
            await engine.dispose()

    asyncio.run(check())
