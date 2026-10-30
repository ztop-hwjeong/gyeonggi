import os
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from typing import cast
from uuid import uuid4

import pytest
from collector_storage.objects import RawObject, RawObjectStore
from sqlalchemy import Column, MetaData, String, Table, create_engine, delete, insert, update
from sqlalchemy.dialects.postgresql import UUID

from sources.blogs.storage import BlogDetailRepository
from sources.blogs.tables import blog_posts, blog_sources, detail_results


class MemoryObjects:
    def __init__(self):
        self.objects = {}

    def put(self, key, body, content_type):
        self.objects[key] = body
        return RawObject(
            bucket="test", key=key, sha256=sha256(body).hexdigest(), byte_length=len(body)
        )

    def read(self, reference):
        return self.objects[reference.key]


@pytest.mark.skipif(
    not os.environ.get("ANALYSIS_TEST_DATABASE_URL"), reason="PostgreSQL 통합 검증 주소 필요"
)
def test_blog_storage_retries_failures_and_preserves_body():
    engine = create_engine(os.environ["ANALYSIS_TEST_DATABASE_URL"], hide_parameters=True)
    meta = MetaData()
    keys = Table(
        "material_keys",
        meta,
        Column("id", UUID(as_uuid=True), primary_key=True),
        Column("kind", String),
        schema="dw",
    )
    source_id = str(uuid4())
    post_id = uuid4()
    seed = {
        "source": "naver_blog",
        "source_id": source_id,
        "url": "https://blog.naver.com/example/1",
        "title": "목록 제목",
        "summary": "목록 요약",
        "published_on": "2026-10-21",
        "blog_name": "검증 블로그",
    }
    try:
        with engine.begin() as connection:
            connection.execute(insert(keys).values(id=post_id, kind="blog"))
            connection.execute(
                insert(blog_posts).values(
                    id=post_id,
                    title=seed["title"],
                    summary=seed["summary"],
                    blog_name=seed["blog_name"],
                    published_on=date(2026, 10, 21),
                )
            )
            connection.execute(
                insert(blog_sources).values(
                    blog_post_id=post_id, source="naver_blog", source_id=source_id, url=seed["url"]
                )
            )
        objects = MemoryObjects()
        repository = BlogDetailRepository(engine, cast(RawObjectStore, objects))
        assert source_id in {
            row["source_id"]
            for row in repository.pending_blog_sources(100, start_date=date(2026, 10, 21))
        }
        assert source_id not in {
            row["source_id"]
            for row in repository.pending_blog_sources(100, start_date=date(2026, 10, 22))
        }
        for index in range(3):
            run_id = uuid4()
            repository.save_run(run_id, {"status": "running"})
            repository.save_result(run_id, seed, {"status": "failed", "reason": "일시적 연결 실패"})
            assert source_id not in {
                row["source_id"] for row in repository.pending_blog_sources(100)
            }
            assert (
                source_id
                in {
                    row["source_id"]
                    for row in repository.pending_blog_sources(100, retry_source_ids=[source_id])
                }
            ) == (index < 2)
            with engine.begin() as connection:
                connection.execute(
                    update(detail_results)
                    .where(
                        detail_results.c.run_id == run_id,
                        detail_results.c.source_id == source_id,
                    )
                    .values(created_at=datetime.now(UTC) - timedelta(hours=2))
                )
            assert (
                source_id in {row["source_id"] for row in repository.pending_blog_sources(100)}
            ) == (index < 2)

        body_id = str(uuid4())
        body_post_id = uuid4()
        body_seed = {**seed, "source_id": body_id}
        with engine.begin() as connection:
            connection.execute(insert(keys).values(id=body_post_id, kind="blog"))
            connection.execute(
                insert(blog_posts).values(
                    id=body_post_id, title="본문 저장", summary="", published_on=date(2026, 10, 21)
                )
            )
            connection.execute(
                insert(blog_sources).values(
                    blog_post_id=body_post_id,
                    source="naver_blog",
                    source_id=body_id,
                    url=seed["url"],
                )
            )
        run_id = uuid4()
        repository.save_run(run_id, {"status": "running"})
        snapshot = repository.save_response(
            run_id, body_seed, "html", seed["url"], 200, "text/html", b"<p>hello</p>"
        )
        assert repository.read_body(snapshot) == b"<p>hello</p>"
        repository.save_result(
            run_id,
            body_seed,
            {"status": "collected"},
            {
                "title": "본문 제목",
                "body": "수집한 블로그 본문",
                "stage": "html",
                "provenance": {"snapshots": [snapshot]},
                "original_published_on": "2026-10-20",
            },
        )
        assert body_id not in {row["source_id"] for row in repository.pending_blog_sources(100)}
        assert body_id not in {
            row["source_id"]
            for row in repository.pending_blog_sources(100, retry_source_ids=[body_id])
        }

        skipped_id = str(uuid4())
        skipped_post_id = uuid4()
        with engine.begin() as connection:
            connection.execute(insert(keys).values(id=skipped_post_id, kind="blog"))
            connection.execute(
                insert(blog_posts).values(
                    id=skipped_post_id,
                    title="영구 스킵",
                    summary="",
                    published_on=date(2026, 10, 21),
                )
            )
            connection.execute(
                insert(blog_sources).values(
                    blog_post_id=skipped_post_id,
                    source="naver_blog",
                    source_id=skipped_id,
                    url=seed["url"],
                )
            )
        run_id = uuid4()
        repository.save_run(run_id, {"status": "running"})
        repository.save_result(
            run_id,
            {**seed, "source_id": skipped_id},
            {"status": "skipped", "skip_reason": "unavailable"},
        )
        assert skipped_id not in {
            row["source_id"]
            for row in repository.pending_blog_sources(100, retry_source_ids=[skipped_id])
        }
    finally:
        engine.dispose()


@pytest.mark.skipif(
    not os.environ.get("ANALYSIS_TEST_DATABASE_URL"), reason="PostgreSQL 통합 검증 주소 필요"
)
def test_pending_blogs_respect_discovery_target_collection_flags():
    engine = create_engine(os.environ["ANALYSIS_TEST_DATABASE_URL"], hide_parameters=True)
    metadata = MetaData()
    keys = Table("material_keys", metadata, schema="dw", autoload_with=engine)
    rules = Table("collection_rules", metadata, schema="ops", autoload_with=engine)
    versions = Table("collection_rule_versions", metadata, schema="ops", autoload_with=engine)
    requests = Table("collection_requests", metadata, schema="ops", autoload_with=engine)
    targets = Table("analysis_targets", metadata, schema="ops", autoload_with=engine)
    reports = Table("analysis_reports", metadata, schema="ops", autoload_with=engine)
    mappings = Table("collection_rule_targets", metadata, schema="ops", autoload_with=engine)
    request_items = Table("collection_request_items", metadata, schema="st", autoload_with=engine)
    key = uuid4().hex
    source_ids = {
        name: f"{name}-{key}"
        for name in ("legacy", "off", "enabled", "shared", "archived", "unmapped")
    }
    post_ids = {name: uuid4() for name in source_ids}
    off_rule, enabled_rule, archived_rule, unmapped_rule = (uuid4() for _ in range(4))
    off_target, enabled_target, archived_target = (uuid4() for _ in range(3))
    request_ids = [uuid4() for _ in range(6)]
    definition = {"name": "검증", "terms": ["교육"], "sources": ["naver_blog"], "enabled": True}
    try:
        with engine.begin() as connection:
            connection.execute(
                insert(keys), [{"id": post_id, "kind": "blog"} for post_id in post_ids.values()]
            )
            connection.execute(
                insert(blog_posts),
                [
                    {
                        "id": post_ids[name],
                        "title": name,
                        "summary": "검증",
                        "published_on": date(2026, 10, 21),
                    }
                    for name in source_ids
                ],
            )
            connection.execute(
                insert(blog_sources),
                [
                    {
                        "blog_post_id": post_ids[name],
                        "source": "naver_blog",
                        "source_id": source_id,
                        "url": f"https://blog.naver.com/{source_id}",
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
                        "source": "naver_blog",
                        "mode": "incremental",
                        "definition": definition,
                        "start_date": date(2026, 10, 21),
                        "end_date": date(2026, 10, 30),
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
        repository = BlogDetailRepository(engine, cast(RawObjectStore, MemoryObjects()))
        pending = {row["source_id"] for row in repository.pending_blog_sources(500)}
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
                delete(reports).where(
                    reports.c.target_id.in_((off_target, enabled_target, archived_target))
                )
            )
            connection.execute(
                delete(targets).where(
                    targets.c.id.in_((off_target, enabled_target, archived_target))
                )
            )
            connection.execute(
                delete(blog_sources).where(blog_sources.c.source_id.in_(tuple(source_ids.values())))
            )
            connection.execute(
                delete(blog_posts).where(blog_posts.c.id.in_(tuple(post_ids.values())))
            )
            connection.execute(delete(keys).where(keys.c.id.in_(tuple(post_ids.values()))))
        engine.dispose()
