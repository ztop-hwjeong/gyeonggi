import os
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from typing import cast
from uuid import uuid4

import pytest
from collector_storage.objects import RawObject, RawObjectStore
from sqlalchemy import Column, MetaData, String, Table, create_engine, insert, update
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
