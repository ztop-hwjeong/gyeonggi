import os
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import MetaData, Table, create_engine, delete, insert, select, update

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
        naver_seed = next(
            seed for seed in repository.pending_naver_news(500) if seed.source_id == f"naver-{key}"
        )
        with repository.acquire_article(naver_seed) as first:
            assert first == "collect"
            with repository.acquire_article(only_bigkinds[0]) as second:
                assert second == "deferred"
        with repository.acquire_article(only_bigkinds[0]) as released:
            assert released == "collect"
    finally:
        engine.dispose()


@pytest.mark.skipif("ANALYSIS_TEST_DATABASE_URL" not in os.environ, reason="전용 검증 DB 필요")
def test_pending_articles_respect_discovery_target_collection_flags():
    engine = create_engine(os.environ["ANALYSIS_TEST_DATABASE_URL"])
    metadata = MetaData()
    search = Table("search_items", metadata, schema="dw", autoload_with=engine)
    keys = Table("material_keys", metadata, schema="dw", autoload_with=engine)
    article_table = Table("articles", metadata, schema="dw", autoload_with=engine)
    rules = Table("collection_rules", metadata, schema="ops", autoload_with=engine)
    versions = Table("collection_rule_versions", metadata, schema="ops", autoload_with=engine)
    requests = Table("collection_requests", metadata, schema="ops", autoload_with=engine)
    targets = Table("analysis_targets", metadata, schema="ops", autoload_with=engine)
    mappings = Table("collection_rule_targets", metadata, schema="ops", autoload_with=engine)
    request_items = Table("collection_request_items", metadata, schema="st", autoload_with=engine)
    key = uuid4().hex
    source_ids = {
        name: f"{name}-{key}"
        for name in ("legacy", "off", "enabled", "shared", "archived", "unmapped")
    }
    article_ids = {name: uuid4() for name in source_ids}
    off_rule, enabled_rule, archived_rule, unmapped_rule = (uuid4() for _ in range(4))
    off_target, enabled_target, archived_target = (uuid4() for _ in range(3))
    request_ids = [uuid4() for _ in range(6)]
    definition = {"name": "검증", "terms": ["교육"], "sources": ["naver_news"], "enabled": True}
    try:
        with engine.begin() as connection:
            connection.execute(
                insert(keys),
                [{"id": article_id, "kind": "news"} for article_id in article_ids.values()],
            )
            connection.execute(
                insert(article_table),
                [
                    {"id": article_ids[name], "title": name, "publisher": "검증언론"}
                    for name in source_ids
                ],
            )
            connection.execute(
                insert(search),
                [
                    {
                        "provider": "naver",
                        "channel": "news",
                        "source_id": source_id,
                        "article_id": article_ids[name],
                        "content_hash": key + name,
                        "data": {
                            "title": name,
                            "summary": "검증",
                            "url": f"https://example.test/{source_id}",
                        },
                    }
                    for name, source_id in source_ids.items()
                ],
            )
            connection.execute(
                insert(rules),
                [
                    {"id": rule_id, "version": 1, "definition": definition}
                    for rule_id in (off_rule, enabled_rule, archived_rule, unmapped_rule)
                ],
            )
            connection.execute(
                insert(versions),
                [
                    {"rule_id": rule_id, "version": 1, "definition": definition}
                    for rule_id in (off_rule, enabled_rule, archived_rule, unmapped_rule)
                ],
            )
            connection.execute(
                insert(targets),
                [
                    {
                        "id": off_target,
                        "kind": "current_issue",
                        "name": f"off-{key}",
                        "collection_enabled": False,
                        "archived_at": None,
                    },
                    {
                        "id": enabled_target,
                        "kind": "regular",
                        "name": f"enabled-{key}",
                        "collection_enabled": True,
                        "archived_at": None,
                    },
                    {
                        "id": archived_target,
                        "kind": "current_issue",
                        "name": f"archived-{key}",
                        "collection_enabled": True,
                        "archived_at": datetime.now(UTC),
                    },
                ],
            )
            connection.execute(
                insert(mappings),
                [
                    {"rule_id": off_rule, "target_id": off_target},
                    {"rule_id": enabled_rule, "target_id": enabled_target},
                    {"rule_id": archived_rule, "target_id": archived_target},
                ],
            )
            request_rules = [
                off_rule,
                enabled_rule,
                off_rule,
                enabled_rule,
                archived_rule,
                unmapped_rule,
            ]
            names = ["off", "enabled", "shared", "shared", "archived", "unmapped"]
            connection.execute(
                insert(requests),
                [
                    {
                        "id": request_id,
                        "rule_id": rule_id,
                        "rule_version": 1,
                        "source": "naver_news",
                        "mode": "incremental",
                        "definition": definition,
                        "start_date": datetime(2026, 10, 21).date(),
                        "end_date": datetime(2026, 10, 30).date(),
                    }
                    for request_id, rule_id in zip(request_ids, request_rules, strict=True)
                ],
            )
            connection.execute(
                insert(request_items),
                [
                    {"request_id": request_id, "source_id": source_ids[name], "data": {}}
                    for request_id, name in zip(request_ids, names, strict=True)
                ],
            )
        pending = {
            seed.source_id for seed in DetailRepository(engine, Mock()).pending_naver_news(500)
        }
        assert source_ids["legacy"] in pending
        assert {source_ids["enabled"], source_ids["shared"], source_ids["unmapped"]} <= pending
        assert source_ids["off"] not in pending
        assert source_ids["archived"] not in pending
    finally:
        with engine.begin() as connection:
            connection.execute(
                delete(request_items).where(request_items.c.request_id.in_(request_ids))
            )
            connection.execute(delete(requests).where(requests.c.id.in_(request_ids)))
            connection.execute(
                delete(mappings).where(
                    mappings.c.rule_id.in_((off_rule, enabled_rule, archived_rule, unmapped_rule))
                )
            )
            connection.execute(
                delete(versions).where(
                    versions.c.rule_id.in_((off_rule, enabled_rule, archived_rule, unmapped_rule))
                )
            )
            connection.execute(
                delete(rules).where(
                    rules.c.id.in_((off_rule, enabled_rule, archived_rule, unmapped_rule))
                )
            )
            connection.execute(
                delete(targets).where(
                    targets.c.id.in_((off_target, enabled_target, archived_target))
                )
            )
            connection.execute(
                delete(search).where(search.c.source_id.in_(tuple(source_ids.values())))
            )
            connection.execute(
                delete(article_table).where(article_table.c.id.in_(tuple(article_ids.values())))
            )
            connection.execute(delete(keys).where(keys.c.id.in_(tuple(article_ids.values()))))
        engine.dispose()
