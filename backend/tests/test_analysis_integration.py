import asyncio
import json
import os
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from domain.analysis.application import AnalysisApplication, AnalysisApplyError
from domain.analysis.registry import TopicRegistry
from domain.analysis.registry_models import ArticleTopicOverride
from domain.analysis.reporting import report_data
from domain.article_workflow.models import SentimentWrite
from domain.article_workflow.relations import ArticleRelations
from domain.article_workflow.repository import ArticleWorkflow


@pytest.mark.skipif(
    not os.environ.get("ANALYSIS_TEST_DATABASE_URL"),
    reason="독립 PostgreSQL 테스트 데이터베이스 필요",
)
def test_flat_article_analysis_preserves_manual_changes_in_report():
    asyncio.run(_check_flat_article_analysis())


async def _check_flat_article_analysis() -> None:
    engine = create_async_engine(os.environ["ANALYSIS_TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    marker = uuid4().hex
    source_id = f"article-{marker}"
    run_id = uuid4()
    tag_name = f"교육 현안 {marker}"
    draft = {
        "tags": [tag_name],
        "sentiment": "긍정",
        "mixed_sentiment": False,
        "sentiment_reason": "지원 확대를 긍정적으로 평가",
    }
    try:
        async with factory() as session:
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
                        "VALUES ('bigkinds',:source_id,:hash,:title,:body,'http',:run_id,'{}')"
                    ),
                    {
                        "source_id": source_id,
                        "hash": marker,
                        "title": f"교육 현안 보도 {marker}",
                        "body": "경기도교육청 정책에 대한 긍정적 평가",
                        "run_id": detail_run_id,
                    },
                )
                article_id = await session.scalar(
                    text(
                        "SELECT article_id FROM dw.article_sources "
                        "WHERE source='bigkinds' AND source_id=:source_id"
                    ),
                    {"source_id": source_id},
                )
                assert article_id is not None
                await session.execute(
                    text(
                        "INSERT INTO ops.analysis_runs"
                        "(id,article_id,source,source_id,content_hash,model,prompt,status,"
                        "catalog_snapshot,model_draft) VALUES "
                        "(:id,:article_id,'bigkinds',:source_id,:hash,'gpt-6-luna',"
                        "'테스트 프롬프트','completed','{}',CAST(:draft AS jsonb))"
                    ),
                    {
                        "id": run_id,
                        "article_id": article_id,
                        "source_id": source_id,
                        "hash": marker,
                        "draft": json.dumps(draft, ensure_ascii=False),
                    },
                )
            registry = TopicRegistry(session)
            application = AnalysisApplication(registry, ArticleWorkflow(session))
            applied = await application.apply(run_id)
            assert applied["sentiment"] == "긍정"
            assert len(applied["tags"]) == 1
            tag_id = applied["tags"][0]
            assert (await registry.canonical_article_topics(article_id))[0].topic_id == tag_id
            assert (await ArticleRelations(session).sentiment(article_id)).origin == "ai"
            await session.commit()

            await registry.override_canonical_article_topic(
                article_id, tag_id, ArticleTopicOverride(decision="exclude")
            )
            await ArticleRelations(session).override_sentiment(
                article_id,
                SentimentWrite(
                    sentiment="중립",
                    mixed_sentiment=True,
                    sentiment_reason="긍정·부정 반응 병기",
                ),
            )
            await session.commit()
            await application.apply(run_id)
            assert await registry.canonical_topic_names(article_id) == []
            effective = await ArticleRelations(session).sentiment(article_id)
            assert effective.origin == "manual"
            assert effective.sentiment == "중립"
            await session.commit()
            report = await report_data(registry, date(2026, 10, 26), [article_id])
            assert report["articles"][0]["keywords"] == ""
            assert report["articles"][0]["sentiment"] == "중립"
            assert report["articles"][0]["reason"] == "긍정·부정 반응 병기"
            bad_run_id = uuid4()
            await session.rollback()
            async with session.begin():
                await session.execute(
                    text(
                        "INSERT INTO ops.analysis_runs"
                        "(id,article_id,source,source_id,content_hash,model,prompt,status,"
                        "catalog_snapshot,model_draft) VALUES "
                        "(:id,:article_id,'bigkinds',:source_id,:hash,'gpt-6-luna',"
                        "'테스트 프롬프트','completed','{}',CAST(:draft AS jsonb))"
                    ),
                    {
                        "id": bad_run_id,
                        "article_id": article_id,
                        "source_id": source_id,
                        "hash": marker,
                        "draft": json.dumps({"tags": ["누락"], "sentiment": "긍정"}),
                    },
                )
            with pytest.raises(AnalysisApplyError, match="형식"):
                await application.apply(bad_run_id)
    finally:
        await engine.dispose()
