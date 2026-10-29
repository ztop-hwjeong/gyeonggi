from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from collector_storage.objects import RawObject, RawObjectStore
from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine

from sources.blogs.tables import (
    blog_contents,
    blog_posts,
    blog_sources,
    detail_results,
    detail_runs,
    responses,
    search_run_items,
)


def _date(value: date | str | None) -> date | None:
    return date.fromisoformat(value) if isinstance(value, str) else value


def _datetime(value: datetime | str | None) -> datetime | None:
    return datetime.fromisoformat(value) if isinstance(value, str) else value


class BlogDetailRepository:
    def __init__(self, engine: Engine, objects: RawObjectStore) -> None:
        self._engine = engine
        self._objects = objects

    def pending_blog_sources(
        self,
        limit: int,
        start_date: date | None = None,
        search_run_id: UUID | None = None,
        retry_source_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        collected = (
            select(blog_contents.c.id)
            .where(blog_contents.c.blog_post_id == blog_sources.c.blog_post_id)
            .exists()
        )
        completed = (
            select(detail_results.c.run_id)
            .where(
                detail_results.c.source == blog_sources.c.source,
                detail_results.c.source_id == blog_sources.c.source_id,
                detail_results.c.result["status"].astext.in_(("collected", "skipped")),
            )
            .exists()
        )
        failed_count = (
            select(func.count())
            .where(
                detail_results.c.source == blog_sources.c.source,
                detail_results.c.source_id == blog_sources.c.source_id,
                detail_results.c.result["status"].astext == "failed",
            )
            .scalar_subquery()
        )
        criteria = [
            ~collected,
            ~completed,
            failed_count < 3,
        ]
        if retry_source_ids is None:
            last_failure = (
                select(func.max(detail_results.c.created_at))
                .where(
                    detail_results.c.source == blog_sources.c.source,
                    detail_results.c.source_id == blog_sources.c.source_id,
                    detail_results.c.result["status"].astext == "failed",
                )
                .scalar_subquery()
            )
            criteria.append(
                or_(
                    last_failure.is_(None),
                    last_failure <= datetime.now(UTC) - timedelta(hours=1),
                )
            )
        else:
            criteria.append(blog_sources.c.source_id.in_(retry_source_ids))
        if start_date is not None:
            criteria.append(blog_posts.c.published_on >= start_date)
        if search_run_id is not None:
            criteria.append(
                select(search_run_items.c.run_id)
                .where(
                    search_run_items.c.run_id == search_run_id,
                    search_run_items.c.source_id == blog_sources.c.source_id,
                )
                .exists()
            )
        statement = (
            select(
                blog_sources.c.source,
                blog_sources.c.source_id,
                func.coalesce(blog_sources.c.original_url, blog_sources.c.url).label("url"),
                blog_posts.c.title,
                blog_posts.c.summary,
                blog_posts.c.blog_name,
                blog_posts.c.blog_url,
                blog_posts.c.published_on,
            )
            .join(blog_posts, blog_posts.c.id == blog_sources.c.blog_post_id)
            .where(*criteria)
            .order_by(blog_sources.c.first_seen_at.desc(), blog_sources.c.source_id)
            .limit(limit)
        )
        with self._engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [
            {
                **row,
                "summary": row["summary"] or "",
                "published_on": row["published_on"].isoformat() if row["published_on"] else None,
            }
            for row in rows
        ]

    def save_run(self, run_id: UUID, summary: dict[str, Any]) -> None:
        statement = insert(detail_runs).values(id=run_id, summary=summary)
        with self._engine.begin() as connection:
            connection.execute(
                statement.on_conflict_do_update(
                    index_elements=[detail_runs.c.id],
                    set_={"summary": statement.excluded.summary},
                )
            )

    def save_response(
        self,
        run_id: UUID,
        seed: dict[str, Any],
        stage: str,
        url: str,
        status: int,
        content_type: str,
        body: bytes,
        retry_after: str | None = None,
    ) -> dict[str, Any]:
        response_id = uuid4()
        snapshot = {
            "response_id": str(response_id),
            "url": url,
            "status_code": status,
            "content_type": content_type,
            "sha256": sha256(body).hexdigest(),
            "received_at": datetime.now(UTC).isoformat(),
            "retry_after": retry_after,
        }
        reference = self._objects.put(f"blogs/{run_id}/{stage}/{response_id}", body, content_type)
        with self._engine.begin() as connection:
            connection.execute(
                insert(responses).values(
                    id=response_id,
                    run_id=run_id,
                    source=seed["source"],
                    source_id=seed["source_id"],
                    stage=stage,
                    seed=seed,
                    metadata=snapshot,
                    raw_object=reference.model_dump(mode="json"),
                )
            )
        return snapshot

    def read_body(self, snapshot: dict[str, Any]) -> bytes:
        with self._engine.connect() as connection:
            raw = connection.execute(
                select(responses.c.raw_object).where(
                    responses.c.id == UUID(snapshot["response_id"])
                )
            ).scalar_one_or_none()
        if raw is None:
            raise LookupError("블로그 원본 응답 없음")
        reference = RawObject.model_validate(raw)
        if reference.sha256 != snapshot["sha256"]:
            raise RuntimeError("블로그 원본 메타데이터 해시 불일치")
        return self._objects.read(reference)

    def save_result(
        self,
        run_id: UUID,
        seed: dict[str, Any],
        result: dict[str, Any],
        extraction: dict[str, Any] | None = None,
    ) -> None:
        if (result["status"] == "collected") != (extraction is not None):
            raise ValueError("본문 수집 상태와 추출 결과 불일치")
        source, source_id = seed["source"], seed["source_id"]
        statement = insert(detail_results).values(
            run_id=run_id, source=source, source_id=source_id, result=result
        )
        with self._engine.begin() as connection:
            post_id = connection.execute(
                select(blog_sources.c.blog_post_id).where(
                    blog_sources.c.source == source,
                    blog_sources.c.source_id == source_id,
                )
            ).scalar_one()
            connection.execute(
                statement.on_conflict_do_update(
                    index_elements=[
                        detail_results.c.run_id,
                        detail_results.c.source,
                        detail_results.c.source_id,
                    ],
                    set_={"result": statement.excluded.result},
                )
            )
            if extraction is None:
                return
            body = extraction["body"].strip()
            if not body:
                raise ValueError("빈 블로그 본문")
            content = insert(blog_contents).values(
                blog_post_id=post_id,
                source=source,
                source_id=source_id,
                content_hash=sha256(body.encode("utf-8")).hexdigest(),
                title=extraction["title"],
                body=body,
                stage=extraction.get("stage", "html"),
                run_id=run_id,
                provenance=extraction.get("provenance", {}),
                original_published_on=_date(extraction.get("original_published_on")),
                original_published_at=_datetime(extraction.get("original_published_at")),
                original_modified_on=_date(extraction.get("original_modified_on")),
                original_modified_at=_datetime(extraction.get("original_modified_at")),
                collected_at=datetime.now(UTC),
            )
            connection.execute(
                content.on_conflict_do_update(
                    index_elements=[
                        blog_contents.c.source,
                        blog_contents.c.source_id,
                        blog_contents.c.content_hash,
                    ],
                    set_={
                        "collected_at": content.excluded.collected_at,
                        "provenance": content.excluded.provenance,
                    },
                )
            )
            connection.execute(
                update(blog_posts).where(blog_posts.c.id == post_id).values(updated_at=func.now())
            )
