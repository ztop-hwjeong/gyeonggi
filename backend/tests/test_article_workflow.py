import asyncio
import json
import os
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from domain.analysis.registry import TopicRegistry, TopicRegistryInvalidMaterialError
from domain.analysis.registry_models import ArticleTopicOverride, Topic
from domain.analysis.reporting import report_data
from domain.article_workflow.models import (
    DecisionWrite,
    FilterRuleWrite,
    ReapplyRequest,
    TargetWrite,
)
from domain.article_workflow.repository import ArticleWorkflow, WorkflowInvalidMaterial
from domain.collection.models import ArticleQuery, MaterialQuery
from domain.collection.reporting import CollectionReporting


@pytest.mark.skipif(
    not os.environ.get("ANALYSIS_TEST_DATABASE_URL"),
    reason="독립 PostgreSQL 테스트 데이터베이스 필요",
)
def test_canonical_sources_rule_priority_and_manual_override():
    async def check() -> None:
        engine = create_async_engine(os.environ["ANALYSIS_TEST_DATABASE_URL"])
        factory = async_sessionmaker(engine, expire_on_commit=False)
        source_id = uuid4().hex
        publisher_url = f"https://example.test/article/{source_id}"
        try:
            async with factory() as session:
                async with session.begin():
                    for source in ("bigkinds", "naver_news"):
                        await session.execute(
                            text(
                                "INSERT INTO dw.news_items(source,source_id,data) "
                                "VALUES (:source,:source_id,CAST(:data AS jsonb))"
                            ),
                            {
                                "source": source,
                                "source_id": f"{source}-{source_id}",
                                "data": json.dumps(
                                    {
                                        "title": f"교권 보호 {source_id}",
                                        "summary": f"경기도교육청 교권 보호 {source_id}",
                                        "original_url": publisher_url,
                                    },
                                    ensure_ascii=False,
                                ),
                            },
                        )
                reporting = CollectionReporting(session)
                page = await reporting.articles(ArticleQuery(q=source_id))
                items = [
                    item
                    for item in page.items
                    if any(source_id in source.source_id for source in item.sources)
                ]
                assert len(items) == 1
                article = items[0]
                assert {source.source for source in article.sources} == {
                    "bigkinds",
                    "naver_news",
                }
                await session.commit()

                workflow = ArticleWorkflow(session)
                target = await workflow.save_target(
                    TargetWrite(kind="policy", name=f"교권 보호 {source_id}")
                )
                lower = await workflow.save_rule(
                    FilterRuleWrite.model_validate(
                        {
                            "name": "교권 제외",
                            "priority": 8000,
                            "decision": "exclude",
                            "conditions": {"any": [source_id]},
                        }
                    )
                )
                higher = await workflow.save_rule(
                    FilterRuleWrite.model_validate(
                        {
                            "name": "교육청 예외",
                            "priority": 9000,
                            "decision": "include",
                            "conditions": {"all": ["경기도교육청", source_id]},
                        }
                    )
                )
                target_rule = await workflow.save_rule(
                    FilterRuleWrite.model_validate(
                        {
                            "name": "정책 연결",
                            "target_id": target.id,
                            "priority": 8000,
                            "decision": "include",
                            "conditions": {"any": [source_id]},
                        }
                    )
                )
                first = await workflow.evaluate(article.id)
                assert first.inclusion.decision == "include"
                assert first.inclusion.rule_id == higher.id
                assert any(
                    link.target_id == target.id and link.decision == "include"
                    for link in first.targets
                )
                scoped = await reporting.articles(ArticleQuery(target_id=target.id, q=source_id))
                assert [item.id for item in scoped.items] == [article.id]
                await session.commit()
                assert len(await TopicRegistry(session).report_articles(None, target.id)) == 1
                await workflow.delete_rule(higher.id, higher.version)
                assert (await workflow.reapply(ReapplyRequest(scope="all"))).processed_count >= 1
                second = await workflow.inclusion(article.id)
                assert second.decision == "exclude"
                assert second.rule_id == lower.id
                assert await TopicRegistry(session).report_articles(None, target.id) == []
                await workflow.override(
                    article.id, DecisionWrite(decision="include", reason="검토 후 포함")
                )
                third = await workflow.evaluate(article.id)
                assert third.inclusion.origin == "manual"
                assert third.inclusion.decision == "include"
                assert len(await workflow.history(article.id)) >= 3
                data = await report_data(
                    TopicRegistry(session), date(2026, 10, 26), target_id=target.id
                )
                assert len(data["articles"]) == 1
                assert data["articles"][0]["reason"] == ""
                registry = TopicRegistry(session)
                topic_id = f"topic-{source_id}"
                await registry.ensure_topics(
                    [Topic(id=topic_id, name=f"교권 {source_id}", description="교권 보도")]
                )
                await registry.sync_material_tags(article.id, [topic_id])
                assert await registry.canonical_topic_names(article.id) == [f"교권 {source_id}"]
                await registry.override_canonical_article_topic(
                    article.id, topic_id, ArticleTopicOverride(decision="exclude")
                )
                await registry.sync_material_tags(article.id, [topic_id])
                assert await registry.canonical_topic_names(article.id) == []
                await workflow.delete_rule(target_rule.id, target_rule.version)
                reapplied = await workflow.reapply(
                    ReapplyRequest(scope="target", target_id=target.id)
                )
                assert reapplied.processed_count >= 1
                assert await workflow.target_links(article.id) == []
                assert (await workflow.inclusion(article.id)).origin == "manual"
        finally:
            await engine.dispose()

    asyncio.run(check())


@pytest.mark.skipif(
    not os.environ.get("ANALYSIS_TEST_DATABASE_URL"),
    reason="독립 PostgreSQL 테스트 데이터베이스 필요",
)
def test_blog_materials_stay_out_of_news_analysis():
    async def check() -> None:
        engine = create_async_engine(os.environ["ANALYSIS_TEST_DATABASE_URL"])
        factory = async_sessionmaker(engine, expire_on_commit=False)
        marker = uuid4().hex
        try:
            async with factory() as session:
                async with session.begin():
                    for channel in ("blog",):
                        await session.execute(
                            text(
                                "INSERT INTO dw.search_items"
                                "(provider,channel,source_id,content_hash,data) "
                                "VALUES ('naver',:channel,:source_id,:hash,CAST(:data AS jsonb))"
                            ),
                            {
                                "channel": channel,
                                "source_id": f"{channel}-{marker}",
                                "hash": marker,
                                "data": json.dumps(
                                    {
                                        "title": f"교육 소식 {marker}",
                                        "summary": "경기도교육청",
                                        "url": f"https://example.test/{channel}/{marker}",
                                    },
                                    ensure_ascii=False,
                                ),
                            },
                        )
                reporting = CollectionReporting(session)
                posts = await reporting.materials(MaterialQuery(group="posts", q=marker))
                assert {item.kind for item in posts.items} == {"blog"}
                assert posts.total == 1
                assert all(item.summary == "경기도교육청" for item in posts.items)
                assert all(item.content_preview == "" for item in posts.items)
                assert (await reporting.materials(MaterialQuery(group="news", q=marker))).total == 0
                assert (await reporting.articles(ArticleQuery(q=marker))).total == 0
                overview = await reporting.overview()
                assert overview.kind_counts["blog"] >= 1
                assert overview.total_items == sum(overview.kind_counts.values())
                for material in posts.items:
                    assert (await reporting.material(material.id)).kind == material.kind
                await session.commit()
                workflow = ArticleWorkflow(session)
                registry = TopicRegistry(session)
                for material in posts.items:
                    with pytest.raises(WorkflowInvalidMaterial):
                        await workflow.inclusion(material.id)
                    with pytest.raises(WorkflowInvalidMaterial):
                        await workflow.reapply(
                            ReapplyRequest(scope="selected", article_ids=[material.id])
                        )
                    with pytest.raises(TopicRegistryInvalidMaterialError):
                        await registry.canonical_article_topics(material.id)
        finally:
            await engine.dispose()

    asyncio.run(check())
