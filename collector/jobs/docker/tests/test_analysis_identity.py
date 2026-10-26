import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any, LiteralString, cast
from uuid import uuid4

import psycopg
import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration
from prefect.client.orchestration import SyncPrefectClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from analysis.cache import PostgresResponseCache
from analysis.dispatch import dispatch_one
from analysis.models import Article
from analysis.repository import AnalysisRepository


def scalar(connection: psycopg.Connection, sql: LiteralString, params: tuple = ()) -> Any:
    row = connection.execute(sql, params).fetchone()
    assert row is not None
    return row[0]


@pytest.mark.skipif(
    "ANALYSIS_TEST_DATABASE_URL" not in os.environ,
    reason="독립 PostgreSQL 테스트 데이터베이스 필요",
)
def test_article_identity_and_exact_cache_across_sources() -> None:
    dsn = os.environ["ANALYSIS_TEST_DATABASE_URL"]
    suffix = uuid4().hex
    publisher_url = f"https://publisher.test/story/{suffix}"
    source_ids = [f"b-{suffix}", f"n-{suffix}"]

    def save(source: str, source_id: str):
        with psycopg.connect(dsn, autocommit=True) as connection:
            return scalar(
                connection,
                "SELECT dw.resolve_material_source(%s,%s,NULL,%s,%s,NULL,NULL,NULL,"
                "NULL,NULL,NULL,NULL)",
                (source, source_id, publisher_url, "같은 기사"),
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(save, ("bigkinds", "naver_news"), source_ids))
    assert first == second
    with ThreadPoolExecutor(max_workers=2) as pool:
        repeated = list(pool.map(save, ("bigkinds", "bigkinds"), (source_ids[0], source_ids[0])))
    assert repeated == [first, first]

    sqlalchemy_url = dsn.replace("postgresql://", "postgresql+psycopg://", 1)
    async_engine = create_async_engine(sqlalchemy_url)
    sync_engine = create_engine(sqlalchemy_url)
    repository = AnalysisRepository(async_sessionmaker(async_engine))
    content_hash = "b" * 64
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(
            "INSERT INTO ops.analysis_queue_keys(article_id,content_hash,source,source_id) "
            "VALUES (%s,%s,'bigkinds',%s)",
            (first, content_hash, source_ids[0]),
        )
        connection.execute(
            "INSERT INTO ops.analysis_queue(article_id,source,source_id,content_hash) "
            "VALUES (%s,'bigkinds',%s,%s)",
            (first, source_ids[0], content_hash),
        )
    first_article = Article(
        article_id=first,
        source="bigkinds",
        source_id=source_ids[0],
        content_hash=content_hash,
        title="같은 기사",
        body="본문",
    )
    second_article = first_article.model_copy(
        update={"source": "naver_news", "source_id": source_ids[1]}
    )

    async def record_runs():
        class Client:
            def read_deployment_by_name(self, name):
                return SimpleNamespace(id=uuid4())

            def create_flow_run_from_deployment(self, deployment_id, **kwargs):
                assert kwargs["idempotency_key"].startswith("analysis:")
                return SimpleNamespace(id=uuid4())

        assert (
            await dispatch_one(repository, cast(SyncPrefectClient, Client()), "analysis/deployment")
            is True
        )
        run_id, attempt_id = await repository.claim(first_article, None, None)
        await repository.complete(run_id, attempt_id, {"article": {}}, {})
        second_run_id, second_attempt = await repository.claim(second_article, None, None)
        await async_engine.dispose()
        return run_id, attempt_id, second_run_id, second_attempt

    run_id, attempt_id, second_run_id, second_attempt = asyncio.run(
        record_runs(), loop_factory=asyncio.SelectorEventLoop
    )
    assert second_run_id != run_id and second_attempt != attempt_id
    with psycopg.connect(dsn) as connection:
        assert (
            scalar(
                connection,
                "SELECT count(*) FROM ops.analysis_attempts WHERE run_id IN (%s,%s)",
                (run_id, second_run_id),
            )
            == 2
        )

    cache = PostgresResponseCache(sync_engine)
    prompt = f"같은 입력 {suffix}"
    cache.update(prompt, "같은 모델·스키마", [ChatGeneration(message=AIMessage(content="결과"))])
    assert cache.lookup(prompt, "같은 모델·스키마") is None
    cache.commit()
    next_cache = PostgresResponseCache(sync_engine)
    assert next_cache.lookup(prompt, "같은 모델·스키마") is not None
    assert next_cache.hit is True
    assert next_cache.lookup("다른 입력", "같은 모델·스키마") is None

    langchain_cache = PostgresResponseCache(sync_engine)
    model = FakeListChatModel(responses=["첫 응답", "두 번째 호출"], cache=langchain_cache)
    messages = [HumanMessage(content=f"모델 입력 {suffix}")]
    first_response = asyncio.run(model.ainvoke(messages))
    langchain_cache.commit()
    second_response = asyncio.run(model.ainvoke(messages))
    assert first_response.content == second_response.content == "첫 응답"
    assert langchain_cache.hit is True
    sync_engine.dispose()


@pytest.mark.skipif(
    "ANALYSIS_TEST_DATABASE_URL" not in os.environ,
    reason="독립 PostgreSQL 테스트 데이터베이스 필요",
)
def test_late_url_conflict_is_recorded_without_merging_and_homepage_is_ignored() -> None:
    dsn = os.environ["ANALYSIS_TEST_DATABASE_URL"]
    suffix = uuid4().hex
    source_id = f"late-{suffix}"
    other_id = f"keyed-{suffix}"
    publisher_url = f"https://publisher.test/story/{suffix}"
    with psycopg.connect(dsn, autocommit=True) as connection:
        first = scalar(
            connection,
            "SELECT dw.resolve_material_source('bigkinds',%s,NULL,NULL,'A',NULL,NULL,NULL,"
            "NULL,NULL,NULL,NULL)",
            (source_id,),
        )
        second = scalar(
            connection,
            "SELECT dw.resolve_material_source('naver_news',%s,NULL,%s,'A',NULL,NULL,NULL,"
            "NULL,NULL,NULL,NULL)",
            (other_id, publisher_url),
        )
        assert first != second
        assert (
            scalar(
                connection,
                "SELECT dw.resolve_material_source('bigkinds',%s,NULL,%s,'A',NULL,NULL,NULL,"
                "NULL,NULL,NULL,NULL)",
                (source_id, publisher_url),
            )
            == first
        )
        assert (
            scalar(
                connection,
                "SELECT other_material_id FROM dw.material_identity_conflicts "
                "WHERE source='bigkinds' AND source_id=%s",
                (source_id,),
            )
            == second
        )
        assert (
            scalar(
                connection,
                "SELECT dw.canonical_article_url('https://publisher.test/?utm_source=x')",
            )
            is None
        )


@pytest.mark.skipif(
    "ANALYSIS_TEST_DATABASE_URL" not in os.environ,
    reason="독립 PostgreSQL 테스트 데이터베이스 필요",
)
def test_material_kind_metadata_and_news_only_analysis_queue() -> None:
    dsn = os.environ["ANALYSIS_TEST_DATABASE_URL"]
    suffix = uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as connection:
        cafe_id = scalar(
            connection,
            "SELECT dw.resolve_material_source('naver_cafearticle',%s,%s,NULL,'카페글',"
            "NULL,NULL,NULL,'교육 카페',NULL,NULL,NULL)",
            (f"c-{suffix}", f"https://cafe.naver.com/test/{suffix}"),
        )
        blog_id = scalar(
            connection,
            "SELECT dw.resolve_material_source('naver_blog',%s,%s,NULL,'블로그글',"
            "NULL,NULL,NULL,NULL,NULL,'교육 블로그',NULL)",
            (f"l-{suffix}", f"https://blog.naver.com/test/{suffix}"),
        )
        assert connection.execute(
            "SELECT kind,cafe_name,publisher FROM dw.materials WHERE id=%s", (cafe_id,)
        ).fetchone() == ("cafe", "교육 카페", None)
        assert connection.execute(
            "SELECT kind,blog_name,publisher FROM dw.materials WHERE id=%s", (blog_id,)
        ).fetchone() == ("blog", "교육 블로그", None)
        news_id = scalar(
            connection,
            "SELECT dw.resolve_material_source('naver_news',%s,NULL,NULL,'뉴스',"
            "NULL,'언론사',NULL,NULL,NULL,NULL,NULL)",
            (f"n-{suffix}",),
        )
        run_id = uuid4()
        connection.execute(
            "INSERT INTO ops.article_detail_runs(id,summary) VALUES (%s,'{}'::jsonb)",
            (run_id,),
        )
        for source, source_id in (
            ("naver_cafearticle", f"c-{suffix}"),
            ("naver_blog", f"l-{suffix}"),
            ("naver_news", f"n-{suffix}"),
        ):
            connection.execute(
                "INSERT INTO dw.article_contents"
                "(source,source_id,content_hash,title,body,stage,run_id,provenance) "
                "VALUES (%s,%s,%s,'제목','본문','test',%s,'{}'::jsonb)",
                (source, source_id, suffix, run_id),
            )
        assert (
            scalar(
                connection,
                "SELECT count(*) FROM ops.analysis_queue WHERE article_id IN (%s,%s)",
                (cafe_id, blog_id),
            )
            == 0
        )
        assert (
            scalar(
                connection,
                "SELECT count(*) FROM ops.analysis_queue WHERE article_id=%s",
                (news_id,),
            )
            == 1
        )
