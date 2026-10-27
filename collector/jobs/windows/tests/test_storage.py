import os
from datetime import UTC, date, datetime
from hashlib import sha256
from unittest.mock import Mock
from uuid import uuid4

import pytest
from collector_storage.objects import RawObject
from pydantic import HttpUrl
from sqlalchemy import MetaData, Table, create_engine, insert, select

from articles.models import (
    ArticleDetail,
    DetailAttempt,
    DetailRunSummary,
    Evidence,
    ExtractedArticle,
)
from articles.storage import ArticleStore, DetailRepository


@pytest.mark.skipif(
    "ANALYSIS_TEST_DATABASE_URL" not in os.environ,
    reason="전용 PostgreSQL 테스트 데이터베이스 필요",
)
def test_persists_original_dates_without_requeuing_same_content(seed) -> None:
    url = os.environ["ANALYSIS_TEST_DATABASE_URL"].replace(
        "postgresql://", "postgresql+psycopg://", 1
    )
    engine = create_engine(url)
    metadata = MetaData()
    news_items = Table("news_items", metadata, schema="dw", autoload_with=engine)
    articles = Table("articles", metadata, schema="dw", autoload_with=engine)
    article_sources = Table("article_sources", metadata, schema="dw", autoload_with=engine)
    article_contents = Table("article_contents", metadata, schema="dw", autoload_with=engine)
    queue = Table("analysis_queue", metadata, schema="ops", autoload_with=engine)
    queue_keys = Table("analysis_queue_keys", metadata, schema="ops", autoload_with=engine)
    source_id = f"windows-storage-{uuid4()}"
    naver_source_id = f"windows-storage-naver-{uuid4()}"
    original_url = f"https://publisher.example.test/article/{uuid4()}"
    body = "검증된 원문 본문 " * 30
    run_id = uuid4()
    objects = Mock()
    raw = RawObject(
        bucket="test",
        key=f"articles/{run_id}",
        sha256=sha256(body.encode()).hexdigest(),
        byte_length=len(body.encode()),
    )
    objects.put.return_value = raw
    objects.read.return_value = body.encode()
    repository = DetailRepository(engine, objects)
    seeded = seed.model_copy(
        update={"source_id": source_id, "original_url": HttpUrl(original_url)}
    )
    store = ArticleStore(repository, run_id, seeded)
    try:
        with engine.begin() as connection:
            connection.execute(
                insert(news_items).values(
                    source="bigkinds",
                    source_id=source_id,
                    data={
                        "title": seeded.title,
                        "summary": seeded.summary,
                        "publisher": seeded.publisher,
                        "original_url": original_url,
                        "published_on": "2026-10-23",
                    },
                )
            )
            connection.execute(
                insert(news_items).values(
                    source="naver_news",
                    source_id=naver_source_id,
                    data={
                        "title": seeded.title,
                        "summary": seeded.summary,
                        "publisher": seeded.publisher,
                        "original_url": original_url,
                        "published_at": "2026-10-25T01:02:03+09:00",
                    },
                )
            )
        repository.save_run(
            DetailRunSummary(
                run_id=str(run_id),
                status="running",
                started_at=datetime.now(UTC),
                requested_count=1,
            )
        )
        snapshot = store.save_response("curl_cffi", original_url, 200, "text/html", body.encode())
        assert repository.read_body(snapshot) == body.encode()
        repository.save_detail(
            run_id, _detail(seeded, body, datetime(2026, 10, 23, 9, 15, tzinfo=UTC))
        )
        repository.save_detail(
            run_id,
            _detail(
                seeded,
                body,
                datetime(2026, 10, 23, 9, 15, tzinfo=UTC),
                datetime(2026, 10, 24, 10, 20, tzinfo=UTC),
            ),
        )

        with engine.connect() as connection:
            article_id = connection.execute(
                select(article_sources.c.article_id).where(
                    article_sources.c.source == "bigkinds", article_sources.c.source_id == source_id
                )
            ).scalar_one()
            article = connection.execute(
                select(
                    articles.c.original_published_at,
                    articles.c.original_modified_at,
                    articles.c.published_at,
                ).where(articles.c.id == article_id)
            ).one()
            contents = connection.execute(
                select(
                    article_contents.c.original_published_at,
                    article_contents.c.original_modified_at,
                ).where(article_contents.c.article_id == article_id)
            ).one()
            naver_time = connection.execute(
                select(article_sources.c.published_at).where(
                    article_sources.c.source == "naver_news",
                    article_sources.c.source_id == naver_source_id,
                )
            ).scalar_one()
            queue_count = connection.execute(
                select(queue.c.article_id).where(queue.c.article_id == article_id)
            ).all()
            key_count = connection.execute(
                select(queue_keys.c.article_id).where(queue_keys.c.article_id == article_id)
            ).all()
        assert article.original_published_at == datetime(2026, 10, 23, 9, 15, tzinfo=UTC)
        assert article.original_modified_at == datetime(2026, 10, 24, 10, 20, tzinfo=UTC)
        assert article.published_at == article.original_published_at
        assert contents.original_published_at == article.original_published_at
        assert contents.original_modified_at == article.original_modified_at
        assert naver_time == datetime(2026, 10, 24, 16, 2, 3, tzinfo=UTC)
        assert len(queue_count) == 1
        assert len(key_count) == 1
    finally:
        engine.dispose()


def _detail(
    seed, body: str, published_at: datetime, modified_at: datetime | None = None
) -> ArticleDetail:
    extraction = ExtractedArticle(
        title=seed.title,
        text=body,
        method="trafilatura",
        evidence=Evidence(
            verified=True,
            title_score=100,
            snippet_scores=[100],
            snippet_match_fraction=1,
            body_chars=len(body),
            reason="검증됨",
        ),
        original_published_on=date(2026, 10, 23),
        original_published_at=published_at,
        original_modified_on=date(2026, 10, 24) if modified_at else None,
        original_modified_at=modified_at,
    )
    return ArticleDetail(
        seed=seed,
        status="collected",
        selected_stage="curl_cffi",
        attempts=[
            DetailAttempt(
                stage="curl_cffi", status="accepted", reason="검증됨", extraction=extraction
            )
        ],
    )
