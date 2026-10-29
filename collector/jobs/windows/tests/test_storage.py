import os
from datetime import UTC, date, datetime
from hashlib import sha256
from unittest.mock import Mock
from uuid import uuid4

import pytest
from collector_storage.objects import RawObject
from pydantic import HttpUrl
from sqlalchemy import MetaData, Table, create_engine, delete, insert, select, update

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
    seeded = seed.model_copy(update={"source_id": source_id, "original_url": HttpUrl(original_url)})
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


@pytest.mark.skipif("ANALYSIS_TEST_DATABASE_URL" not in os.environ, reason="전용 검증 DB 필요")
@pytest.mark.parametrize("source", ["naver_news", "bigkinds"])
def test_unknown_publisher_keeps_body_and_binds_after_registration(seed, source):
    engine = create_engine(os.environ["ANALYSIS_TEST_DATABASE_URL"])
    metadata = MetaData()
    catalog = Table("publishers", metadata, schema="dw", autoload_with=engine)
    domains = Table("publisher_domains", metadata, schema="dw", autoload_with=engine)
    articles = Table("articles", metadata, schema="dw", autoload_with=engine)
    contents = Table("article_contents", metadata, schema="dw", autoload_with=engine)
    results = Table("article_detail_results", metadata, schema="st", autoload_with=engine)
    listing = Table(
        "search_items" if source == "naver_news" else "news_items",
        metadata,
        schema="dw",
        autoload_with=engine,
    )
    key = uuid4().hex
    domain = f"{key}.example"
    run_id = uuid4()
    seeded = seed.model_copy(
        update={
            "source": source,
            "source_id": key,
            "publisher_code": domain,
            "original_url": HttpUrl(f"https://www.{domain}:443/article"),
        }
    )
    repository = DetailRepository(engine, Mock())
    body = "검증된 본문과 독립적으로 관리하는 언론사 정보 " * 30
    try:
        data = seeded.model_dump(mode="json") | {
            "url": str(seeded.original_url),
            "publisher_domain": domain,
        }
        values = (
            {"provider": "naver", "channel": "news", "content_hash": key}
            if source == "naver_news"
            else {"source": source}
        )
        with engine.begin() as connection:
            connection.execute(insert(listing).values(source_id=key, data=data, **values))
        repository.save_run(
            DetailRunSummary(
                run_id=str(run_id),
                status="running",
                started_at=datetime.now(UTC),
                requested_count=1,
            )
        )
        detail = _detail(seeded, body, datetime.now(UTC))
        repository.save_detail(run_id, detail)
        with engine.connect() as connection:
            article_id = connection.scalar(
                select(contents.c.article_id).where(
                    contents.c.source == source, contents.c.source_id == key
                )
            )
            assert article_id is not None
            assert (
                connection.scalar(
                    select(articles.c.publisher_code).where(articles.c.id == article_id)
                )
                is None
            )
            assert connection.scalar(select(catalog.c.code).where(catalog.c.code == domain)) is None
            assert (
                connection.scalar(
                    select(contents.c.body).where(contents.c.article_id == article_id)
                )
                == body
            )
            stored = connection.scalar(
                select(results.c.result).where(
                    results.c.run_id == run_id, results.c.source_id == key
                )
            )
            assert stored is not None and stored["seed"]["publisher_code"] == domain
        registered = "9004" if source == "naver_news" else "9006"
        with engine.begin() as connection:
            connection.execute(
                insert(catalog).values(
                    code=registered, name="등록 언론사", category_code="online_specialty"
                )
            )
            connection.execute(insert(domains).values(domain=domain, publisher_code=registered))
        with engine.connect() as connection:
            row = connection.execute(
                select(articles.c.publisher_code, articles.c.publisher).where(
                    articles.c.id == article_id
                )
            ).one()
            assert (row.publisher_code, row.publisher) == (registered, "등록 언론사")
        replacement = "9005" if source == "naver_news" else "9007"
        with engine.begin() as connection:
            connection.execute(
                insert(catalog).values(
                    code=replacement, name="변경 언론사", category_code="online_specialty"
                )
            )
            connection.execute(
                update(domains).where(domains.c.domain == domain).values(publisher_code=replacement)
            )
        repository.save_detail(run_id, detail)
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    select(articles.c.publisher_code).where(articles.c.id == article_id)
                )
                == replacement
            )
            assert (
                len(
                    connection.execute(
                        select(contents.c.id).where(contents.c.article_id == article_id)
                    ).all()
                )
                == 1
            )
    finally:
        engine.dispose()


@pytest.mark.skipif("ANALYSIS_TEST_DATABASE_URL" not in os.environ, reason="전용 검증 DB 필요")
def test_no_text_skip_keeps_metadata_without_queueing_analysis_or_retry(seed):
    engine = create_engine(os.environ["ANALYSIS_TEST_DATABASE_URL"])
    metadata = MetaData()
    news = Table("news_items", metadata, schema="dw", autoload_with=engine)
    sources = Table("article_sources", metadata, schema="dw", autoload_with=engine)
    contents = Table("article_contents", metadata, schema="dw", autoload_with=engine)
    queue = Table("analysis_queue", metadata, schema="ops", autoload_with=engine)
    results = Table("article_detail_results", metadata, schema="st", autoload_with=engine)
    key, run_id = uuid4().hex, uuid4()
    seeded = seed.model_copy(
        update={"source_id": key, "original_url": HttpUrl(f"https://news.example/{key}")}
    )
    repository = DetailRepository(engine, Mock())
    try:
        with engine.begin() as connection:
            connection.execute(
                insert(news).values(
                    source="bigkinds", source_id=key, data=seeded.model_dump(mode="json")
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
        repository.save_detail(
            run_id,
            ArticleDetail(
                seed=seeded,
                status="skipped",
                selected_stage=None,
                skip_reason="no_text_body",
                attempts=[
                    DetailAttempt(
                        stage="browser_rendered",
                        status="skipped",
                        reason="영상 제공·텍스트 본문 없음",
                        skip_reason="no_text_body",
                    )
                ],
            ),
        )
        with engine.connect() as connection:
            original = connection.execute(
                select(sources).where(sources.c.source == "bigkinds", sources.c.source_id == key)
            ).one()
            assert original.original_url == str(seeded.original_url)
            assert (
                connection.scalar(
                    select(contents.c.id).where(contents.c.article_id == original.article_id)
                )
                is None
            )
            assert (
                connection.scalar(
                    select(queue.c.article_id).where(queue.c.article_id == original.article_id)
                )
                is None
            )
            result = connection.scalar(
                select(results.c.result).where(
                    results.c.run_id == run_id, results.c.source_id == key
                )
            )
            assert result is not None and result["status"] == "skipped"
            assert result["skip_reason"] == "no_text_body"
        assert all(item.source_id != key for item in repository.pending_articles(500))
    finally:
        engine.dispose()


@pytest.mark.skipif(
    "ANALYSIS_TEST_DATABASE_URL" not in os.environ,
    reason="전용 PostgreSQL 테스트 데이터베이스 필요",
)
def test_browser_policy_uses_exact_normalized_host() -> None:
    engine = create_engine(os.environ["ANALYSIS_TEST_DATABASE_URL"])
    metadata = MetaData()
    policies = Table("article_browser_policies", metadata, schema="ops", autoload_with=engine)
    domain = f"www.{uuid4().hex}.example"
    repository = DetailRepository(engine, Mock())
    try:
        assert not repository.allows_rendered_browser(f"https://{domain}/article")
        with engine.begin() as connection:
            connection.execute(
                insert(policies).values(
                    domain=domain,
                    browser_mode="rendered_after_http_failure",
                    reason="HTTP 본문 검증 실패 후 브라우저 본문 확보",
                    evidence={"curl_cffi": {"accepted": 0}, "browser_rendered": {"accepted": 1}},
                )
            )
        assert repository.allows_rendered_browser(f"https://{domain.upper()}/article")
        assert not repository.allows_rendered_browser(f"https://sub.{domain}/article")
    finally:
        with engine.begin() as connection:
            connection.execute(delete(policies).where(policies.c.domain == domain))
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
