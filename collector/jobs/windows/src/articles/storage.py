from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

import psycopg
from collector_storage.config import DatabaseSettings
from collector_storage.objects import RawObject, RawObjectStore
from psycopg.types.json import Jsonb
from pydantic import SecretStr

from articles.models import (
    ArticleDetail,
    ArticleSeed,
    DetailAttempt,
    DetailRunSummary,
    DetailStage,
    FetchSnapshot,
)


class DetailRepository:
    def __init__(
        self, settings: DatabaseSettings, password: SecretStr, objects: RawObjectStore
    ) -> None:
        self._settings = settings
        self._password = password
        self._objects = objects

    def connect(self) -> psycopg.Connection:
        return psycopg.connect(
            host=self._settings.database_host,
            port=self._settings.database_port,
            dbname=self._settings.database_name,
            user=self._settings.database_user,
            password=self._password.get_secret_value(),
            connect_timeout=5,
        )

    def save_run(self, summary: DetailRunSummary) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO ops.article_detail_runs (id, summary) VALUES (%s, %s) "
                "ON CONFLICT (id) DO UPDATE SET summary = EXCLUDED.summary",
                (UUID(summary.run_id), Jsonb(summary.model_dump(mode="json"))),
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
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO st.article_responses "
                "(id, run_id, source_id, stage, seed, metadata, raw_object) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (
                    snapshot.response_id,
                    run_id,
                    seed.source_id,
                    stage,
                    Jsonb(seed.model_dump(mode="json")),
                    Jsonb(snapshot.model_dump(mode="json")),
                    Jsonb(reference.model_dump(mode="json")),
                ),
            )
        return snapshot

    def read_body(self, snapshot: FetchSnapshot) -> bytes:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT raw_object FROM st.article_responses WHERE id = %s",
                (snapshot.response_id,),
            ).fetchone()
        if row is None:
            raise LookupError("수집 원본 응답 없음")
        reference = RawObject.model_validate(row[0])
        if reference.sha256 != snapshot.sha256:
            raise RuntimeError("수집 원본 메타데이터 해시 불일치")
        return self._objects.read(reference)

    def save_attempt(self, run_id: UUID, seed: ArticleSeed, attempt: DetailAttempt) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO st.article_detail_attempts (run_id, source_id, stage, result) "
                "VALUES (%s,%s,%s,%s) ON CONFLICT (run_id, source_id, stage) "
                "DO UPDATE SET result = EXCLUDED.result",
                (run_id, seed.source_id, attempt.stage, Jsonb(attempt.model_dump(mode="json"))),
            )

    def save_detail(self, run_id: UUID, result: ArticleDetail) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO st.article_detail_results (run_id, source_id, result) "
                "VALUES (%s,%s,%s) "
                "ON CONFLICT (run_id, source_id) DO UPDATE SET result = EXCLUDED.result",
                (run_id, result.seed.source_id, Jsonb(result.model_dump(mode="json"))),
            )
            selected = next((item for item in result.attempts if item.status == "accepted"), None)
            if selected is not None and selected.extraction is not None:
                content = selected.extraction
                digest = sha256(content.text.encode()).hexdigest()
                connection.execute(
                    "INSERT INTO dw.article_contents "
                    "(source, source_id, content_hash, title, body, stage, run_id, provenance) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (source, source_id, content_hash) DO NOTHING",
                    (
                        result.seed.source,
                        result.seed.source_id,
                        digest,
                        content.title,
                        content.text,
                        selected.stage,
                        run_id,
                        Jsonb(selected.model_dump(mode="json")),
                    ),
                )

    def read_profile(self, scope: str, identifier: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT properties FROM ops.publisher_adaptive_profiles "
                "WHERE scope = %s AND identifier = %s",
                (scope, identifier),
            ).fetchone()
        return row[0] if row is not None else None

    def save_profile(self, scope: str, identifier: str, properties: dict, context: dict) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO ops.publisher_adaptive_profiles "
                "(scope, identifier, properties, context) "
                "VALUES (%s,%s,%s,%s) ON CONFLICT (scope, identifier) DO UPDATE "
                "SET properties=EXCLUDED.properties, context=EXCLUDED.context, updated_at=now()",
                (scope, identifier, Jsonb(properties), Jsonb(context)),
            )
            connection.execute(
                "INSERT INTO ops.publisher_adaptive_history "
                "(id, scope, identifier, properties, context) "
                "VALUES (%s,%s,%s,%s,%s)",
                (uuid4(), scope, identifier, Jsonb(properties), Jsonb(context)),
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
