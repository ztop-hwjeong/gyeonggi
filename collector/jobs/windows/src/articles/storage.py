from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from collector_storage.objects import RawObject, RawObjectStore
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine

from articles.models import (
    ArticleDetail,
    ArticleSeed,
    DetailAttempt,
    DetailRunSummary,
    DetailStage,
    FetchSnapshot,
)
from articles.tables import (
    adaptive_history,
    adaptive_profiles,
    article_contents,
    attempts,
    detail_results,
    detail_runs,
    responses,
)


class DetailRepository:
    def __init__(self, engine: Engine, objects: RawObjectStore) -> None:
        self._engine = engine
        self._objects = objects

    def save_run(self, summary: DetailRunSummary) -> None:
        statement = insert(detail_runs).values(
            id=UUID(summary.run_id), summary=summary.model_dump(mode="json")
        )
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
        seed: ArticleSeed,
        stage: DetailStage,
        url: str,
        status: int,
        content_type: str,
        body: bytes,
        retry_after: str | None,
    ) -> FetchSnapshot:
        snapshot = FetchSnapshot(
            response_id=uuid4(),
            url=url,
            status_code=status,
            content_type=content_type,
            sha256=sha256(body).hexdigest(),
            received_at=datetime.now(UTC),
            retry_after=retry_after,
        )
        reference = self._objects.put(
            f"articles/{run_id}/{stage}/{snapshot.response_id}", body, content_type
        )
        with self._engine.begin() as connection:
            connection.execute(
                insert(responses).values(
                    id=snapshot.response_id,
                    run_id=run_id,
                    source_id=seed.source_id,
                    stage=stage,
                    seed=seed.model_dump(mode="json"),
                    metadata=snapshot.model_dump(mode="json"),
                    raw_object=reference.model_dump(mode="json"),
                )
            )
        return snapshot

    def read_body(self, snapshot: FetchSnapshot) -> bytes:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(responses.c.raw_object).where(responses.c.id == snapshot.response_id)
            ).scalar_one_or_none()
        if row is None:
            raise LookupError("수집 원본 응답 없음")
        reference = RawObject.model_validate(row)
        if reference.sha256 != snapshot.sha256:
            raise RuntimeError("수집 원본 메타데이터 해시 불일치")
        return self._objects.read(reference)

    def save_attempt(self, run_id: UUID, seed: ArticleSeed, attempt: DetailAttempt) -> None:
        statement = insert(attempts).values(
            run_id=run_id,
            source_id=seed.source_id,
            stage=attempt.stage,
            result=attempt.model_dump(mode="json"),
        )
        with self._engine.begin() as connection:
            connection.execute(
                statement.on_conflict_do_update(
                    index_elements=[attempts.c.run_id, attempts.c.source_id, attempts.c.stage],
                    set_={"result": statement.excluded.result},
                )
            )

    def save_detail(self, run_id: UUID, result: ArticleDetail) -> None:
        result_statement = insert(detail_results).values(
            run_id=run_id,
            source_id=result.seed.source_id,
            result=result.model_dump(mode="json"),
        )
        with self._engine.begin() as connection:
            connection.execute(
                result_statement.on_conflict_do_update(
                    index_elements=[detail_results.c.run_id, detail_results.c.source_id],
                    set_={"result": result_statement.excluded.result},
                )
            )
            selected = next((item for item in result.attempts if item.status == "accepted"), None)
            if selected is not None and selected.extraction is not None:
                content = selected.extraction
                digest = sha256(content.text.encode()).hexdigest()
                content_statement = insert(article_contents).values(
                    source=result.seed.source,
                    source_id=result.seed.source_id,
                    content_hash=digest,
                    title=content.title,
                    body=content.text,
                    stage=selected.stage,
                    run_id=run_id,
                    provenance=selected.model_dump(mode="json"),
                    original_published_on=content.original_published_on,
                    original_published_at=content.original_published_at,
                    original_modified_on=content.original_modified_on,
                    original_modified_at=content.original_modified_at,
                    collected_at=datetime.now(UTC),
                )
                connection.execute(
                    content_statement.on_conflict_do_update(
                        index_elements=[
                            article_contents.c.source,
                            article_contents.c.source_id,
                            article_contents.c.content_hash,
                        ],
                        set_={
                            "original_published_on": (
                                func.coalesce(
                                    content_statement.excluded.original_published_on,
                                    article_contents.c.original_published_on,
                                )
                            ),
                            "original_published_at": (
                                func.coalesce(
                                    content_statement.excluded.original_published_at,
                                    article_contents.c.original_published_at,
                                )
                            ),
                            "original_modified_on": (
                                func.coalesce(
                                    content_statement.excluded.original_modified_on,
                                    article_contents.c.original_modified_on,
                                )
                            ),
                            "original_modified_at": (
                                func.coalesce(
                                    content_statement.excluded.original_modified_at,
                                    article_contents.c.original_modified_at,
                                )
                            ),
                            "collected_at": content_statement.excluded.collected_at,
                            "provenance": content_statement.excluded.provenance,
                        },
                    )
                )

    def read_profile(self, scope: str, identifier: str) -> dict[str, Any] | None:
        with self._engine.connect() as connection:
            return connection.execute(
                select(adaptive_profiles.c.properties).where(
                    adaptive_profiles.c.scope == scope,
                    adaptive_profiles.c.identifier == identifier,
                )
            ).scalar_one_or_none()

    def save_profile(self, scope: str, identifier: str, properties: dict, context: dict) -> None:
        statement = insert(adaptive_profiles).values(
            scope=scope, identifier=identifier, properties=properties, context=context
        )
        with self._engine.begin() as connection:
            connection.execute(
                statement.on_conflict_do_update(
                    index_elements=[adaptive_profiles.c.scope, adaptive_profiles.c.identifier],
                    set_={
                        "properties": statement.excluded.properties,
                        "context": statement.excluded.context,
                    },
                )
            )
            connection.execute(
                insert(adaptive_history).values(
                    id=uuid4(),
                    scope=scope,
                    identifier=identifier,
                    properties=properties,
                    context=context,
                )
            )


class ArticleStore:
    def __init__(self, repository: DetailRepository, run_id: UUID, seed: ArticleSeed) -> None:
        self.repository = repository
        self._run_id = run_id
        self._seed = seed

    def save_response(
        self,
        stage: DetailStage,
        url: str,
        status: int,
        content_type: str,
        body: bytes,
        retry_after: str | None = None,
    ) -> FetchSnapshot:
        return self.repository.save_response(
            self._run_id, self._seed, stage, url, status, content_type, body, retry_after
        )
