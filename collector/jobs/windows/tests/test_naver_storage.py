import os
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import MetaData, Table, create_engine, insert, select, update

from articles.models import (
    ArticleDetail,
    DetailAttempt,
    DetailRunSummary,
    Evidence,
    ExtractedArticle,
)
from articles.storage import DetailRepository


@pytest.mark.skipif(
    "ANALYSIS_TEST_DATABASE_URL" not in os.environ,
    reason="전용 PostgreSQL 테스트 데이터베이스 필요",
)
def test_pending_news_excludes_collected_and_retries_failed_after_cooldown():
    engine = create_engine(os.environ["ANALYSIS_TEST_DATABASE_URL"])
    metadata = MetaData()
    search = Table("search_items", metadata, schema="dw", autoload_with=engine)
    news = Table("news_items", metadata, schema="dw", autoload_with=engine)
    sources = Table("article_sources", metadata, schema="dw", autoload_with=engine)
    articles = Table("articles", metadata, schema="dw", autoload_with=engine)
    streams = Table("search_streams", metadata, schema="ops", autoload_with=engine)
    runs = Table("search_runs", metadata, schema="ops", autoload_with=engine)
    responses = Table("search_responses", metadata, schema="st", autoload_with=engine)
    run_items = Table("search_run_items", metadata, schema="st", autoload_with=engine)
    publishers = Table("publishers", metadata, schema="dw", autoload_with=engine)
    domains = Table("publisher_domains", metadata, schema="dw", autoload_with=engine)
    detail_runs = Table("article_detail_runs", metadata, schema="ops", autoload_with=engine)
    repository = DetailRepository(engine, Mock())
    prefix = str(uuid4())
    run_id = uuid4()
    timestamp = datetime.fromisoformat("2026-10-28T15:30:00+09:00")

    def data(name):
        return {
            "title": "경기도교육청 명사 특강",
            "summary": "원문 대조를 위한 검색 요약",
            "url": f"https://n.news.naver.com/article/test/{prefix}-{name}",
            "original_url": f"https://publisher.example/{prefix}/{name}",
            "published_at": timestamp.isoformat(),
            "publisher_code": "publisher.example",
        }

    try:
        with engine.begin() as connection:
            connection.execute(
                insert(publishers).values(
                    code="9003", name="테스트언론", category_code="online_specialty"
                )
            )
            connection.execute(
                insert(domains).values(domain="publisher.example", publisher_code="9003")
            )
            for name in ("pending", "duplicate", "collected", "failed"):
                listing = data("pending" if name == "duplicate" else name)
                connection.execute(
                    insert(search).values(
                        provider="naver",
                        channel="news",
                        source_id=f"{prefix}-{name}",
                        content_hash=name,
                        data=listing,
                    )
                )
            connection.execute(
                insert(news).values(
                    source="bigkinds",
                    source_id=f"{prefix}-bigkinds-collected",
                    data=data("collected"),
                )
            )
            connection.execute(
                insert(search).values(
                    provider="naver",
                    channel="blog",
                    source_id=f"{prefix}-blog",
                    content_hash="blog",
                    data={"title": "블로그", "url": f"https://blog.example/{prefix}"},
                )
            )
            connection.execute(
                insert(streams).values(
                    stream_key=prefix,
                    provider="naver",
                    channel="news",
                    query="황현필",
                )
            )
            connection.execute(insert(runs).values(id=run_id, stream_key=prefix, summary={}))
            response_id = uuid4()
            connection.execute(
                insert(responses).values(
                    id=response_id,
                    run_id=run_id,
                    start_position=1,
                    status_code=200,
                    metadata={},
                    raw_object={},
                )
            )
            connection.execute(
                insert(run_items).values(
                    run_id=run_id,
                    source_id=f"{prefix}-pending",
                    response_id=response_id,
                    data=data("pending"),
                    is_new=True,
                    is_updated=False,
                )
            )
        repository.save_run(
            DetailRunSummary(
                run_id=str(run_id),
                status="running",
                started_at=datetime.now(UTC),
                requested_count=2,
            )
        )
        seeds = {seed.source_id: seed for seed in repository.pending_naver_news(500)}
        # 같은 원문을 가리키는 네이버 URL은 한 번만 수집하는 범위
        pending_ids = {f"{prefix}-pending", f"{prefix}-duplicate"}
        assert len(pending_ids & seeds.keys()) == 1
        assert f"{prefix}-blog" not in seeds
        assert [seed.source_id for seed in repository.pending_naver_news(10, run_id)] == [
            f"{prefix}-pending"
        ]
        collected = seeds[f"{prefix}-collected"]
        failed = seeds[f"{prefix}-failed"]
        body = "검증된 기사 본문 " * 30
        extraction = ExtractedArticle(
            title=collected.title,
            text=body,
            method="trafilatura",
            evidence=Evidence(
                verified=True,
                title_score=100,
                snippet_scores=[100],
                snippet_match_fraction=1,
                body_chars=len(body),
                reason="검증",
            ),
        )
        repository.save_detail(
            run_id,
            ArticleDetail(
                seed=collected.model_copy(update={"publisher": "테스트언론"}),
                status="collected",
                selected_stage="curl_cffi",
                attempts=[
                    DetailAttempt(
                        stage="curl_cffi",
                        status="accepted",
                        reason="검증",
                        extraction=extraction,
                    )
                ],
            ),
        )
        repository.save_detail(
            run_id,
            ArticleDetail(
                seed=failed,
                status="failed",
                selected_stage=None,
                attempts=[DetailAttempt(stage="curl_cffi", status="failed", reason="HTTP 429")],
            ),
        )
        remaining = {seed.source_id for seed in repository.pending_naver_news(500)}
        assert f"{prefix}-collected" not in remaining
        assert f"{prefix}-failed" not in remaining
        assert len(pending_ids & remaining) == 1
        assert f"{prefix}-bigkinds-collected" not in {
            seed.source_id for seed in repository.pending_articles(500, "bigkinds")
        }
        with engine.begin() as connection:
            connection.execute(
                update(detail_runs)
                .where(detail_runs.c.id == run_id)
                .values(created_at=datetime.now(UTC) - timedelta(hours=1, seconds=1))
            )
        retried = {seed.source_id for seed in repository.pending_naver_news(500)}
        assert f"{prefix}-failed" in retried
        with engine.connect() as connection:
            stored = connection.execute(
                select(articles.c.publisher, articles.c.publisher_code, sources.c.published_at)
                .join(sources, sources.c.article_id == articles.c.id)
                .where(sources.c.source == "naver_news", sources.c.source_id == collected.source_id)
            ).one()
        assert stored.publisher == "테스트언론"
        assert stored.publisher_code == "9003"
        assert stored.published_at == timestamp
    finally:
        engine.dispose()


@pytest.mark.skipif("ANALYSIS_TEST_DATABASE_URL" not in os.environ, reason="전용 검증 DB 필요")
def test_pending_articles_deduplicates_the_same_article_across_sources():
    engine = create_engine(os.environ["ANALYSIS_TEST_DATABASE_URL"])
    metadata = MetaData()
    search = Table("search_items", metadata, schema="dw", autoload_with=engine)
    news = Table("news_items", metadata, schema="dw", autoload_with=engine)
    key = uuid4().hex
    data = {
        "title": "같은 기사",
        "summary": "같은 기사 요약",
        "publisher": "언론사",
        "url": f"https://n.news.naver.com/article/test/{key}",
        "original_url": f"https://publisher.example/{key}",
        "published_on": "2026-10-28",
    }
    try:
        with engine.begin() as connection:
            connection.execute(
                insert(search).values(
                    provider="naver",
                    channel="news",
                    source_id=f"naver-{key}",
                    content_hash="hash",
                    data=data,
                )
            )
            connection.execute(
                insert(news).values(source="bigkinds", source_id=f"bigkinds-{key}", data=data)
            )
            connection.execute(
                insert(news).values(
                    source="bigkinds",
                    source_id=f"older-{key}",
                    data=data | {"original_url": f"https://publisher.example/older-{key}"},
                    first_seen_at=datetime.now(UTC) - timedelta(days=1),
                )
            )
        repository = DetailRepository(engine, Mock())
        newest = repository.pending_articles(1)
        assert newest[0].source_id in {f"naver-{key}", f"bigkinds-{key}"}
        all_sources = [
            seed
            for seed in repository.pending_articles(500)
            if seed.source_id in {f"naver-{key}", f"bigkinds-{key}"}
        ]
        assert len(all_sources) == 1
        only_bigkinds = [
            seed
            for seed in repository.pending_articles(500, "bigkinds")
            if seed.source_id == f"bigkinds-{key}"
        ]
        assert len(only_bigkinds) == 1 and only_bigkinds[0].source == "bigkinds"
    finally:
        engine.dispose()
