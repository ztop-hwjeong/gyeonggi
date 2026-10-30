from collections.abc import Generator
from contextlib import contextmanager
from uuid import UUID, uuid4

import psycopg
from collector_storage.config import DatabaseSettings
from collector_storage.objects import RawObjectStore
from psycopg.rows import DictRow, dict_row
from psycopg.types.json import Jsonb
from pydantic import SecretStr
from sqlalchemy import exists, func, not_, or_, select, update
from sqlalchemy.engine import Engine

from control.models import CollectionCancelled, ManagedRequest
from control.tables import (
    analysis_targets,
    collection_requests,
    collection_rule_targets,
    collection_rules,
)


class ControlRepository:
    def __init__(
        self, settings: DatabaseSettings, password: SecretStr, engine: Engine
    ) -> None:
        self.settings, self.password = settings, password
        self._engine = engine

    def engine(self) -> Engine:
        return self._engine

    @staticmethod
    def _collectable_rule(rule_id):
        mapped = exists(
            select(collection_rule_targets.c.rule_id).where(
                collection_rule_targets.c.rule_id == rule_id
            )
        )
        active = exists(
            select(collection_rule_targets.c.rule_id)
            .join(analysis_targets, analysis_targets.c.id == collection_rule_targets.c.target_id)
            .where(
                collection_rule_targets.c.rule_id == rule_id,
                analysis_targets.c.archived_at.is_(None),
                analysis_targets.c.collection_enabled.is_(True),
            )
        )
        return or_(not_(mapped), active)

    def enabled_rules(self) -> list[UUID]:
        statement = select(collection_rules.c.id).where(
            collection_rules.c.definition["enabled"].astext == "true",
            self._collectable_rule(collection_rules.c.id),
        )
        with self.engine().connect() as connection:
            return list(connection.scalars(statement))

    @contextmanager
    def connect(self) -> Generator[psycopg.Connection[DictRow]]:
        with psycopg.Connection[DictRow].connect(
            host=self.settings.database_host,
            port=self.settings.database_port,
            dbname=self.settings.database_name,
            user=self.settings.database_user,
            password=self.password.get_secret_value(),
            autocommit=True,
            connect_timeout=5,
            row_factory=dict_row,
            options="-c statement_timeout=5000",
        ) as connection:
            yield connection

    def start(self, request_id: UUID, flow_run_id: UUID) -> ManagedRequest | None:
        statement = (
            update(collection_requests)
            .where(
                collection_requests.c.id == request_id,
                collection_requests.c.status.in_(("queued", "submitted")),
                or_(
                    collection_requests.c.flow_run_id.is_(None),
                    collection_requests.c.flow_run_id == flow_run_id,
                ),
                or_(
                    collection_requests.c.mode == "preview",
                    collection_requests.c.rule_id.is_(None),
                    self._collectable_rule(collection_requests.c.rule_id),
                ),
            )
            .values(status="running", flow_run_id=flow_run_id, updated_at=func.now())
            .returning(collection_requests)
        )
        with self.engine().begin() as connection:
            row = connection.execute(statement).mappings().one_or_none()
        return ManagedRequest.model_validate(row) if row else None

    def check_cancelled(self, request_id: UUID) -> None:
        statement = select(collection_requests.c.id).where(
            collection_requests.c.id == request_id,
            collection_requests.c.status.not_in(("cancelling", "cancelled")),
            or_(
                collection_requests.c.mode == "preview",
                collection_requests.c.rule_id.is_(None),
                self._collectable_rule(collection_requests.c.rule_id),
            ),
        )
        with self.engine().connect() as connection:
            if connection.scalar(statement) is None:
                raise CollectionCancelled

    def finish(
        self, request_id: UUID, status: str, summary: dict, error: str | None = None
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE ops.collection_requests SET status=CASE WHEN status='cancelling' "
                "THEN 'cancelled' ELSE %s END,summary=summary || %s,error=%s,updated_at=now() "
                "WHERE id=%s AND status IN ('running','cancelling')",
                (status, Jsonb(summary), error, request_id),
            )

    def save_items(self, request: ManagedRequest, items: list[dict]) -> None:
        with self.connect() as conn, conn.transaction():
            for item in items:
                conn.execute(
                    "INSERT INTO st.collection_request_items(request_id,source_id,data) "
                    "VALUES (%s,%s,%s) ON CONFLICT(request_id,source_id) DO UPDATE "
                    "SET data=EXCLUDED.data",
                    (request.id, item["source_id"], Jsonb(item)),
                )
                if request.mode != "preview" and request.source == "bigkinds":
                    conn.execute(
                        "INSERT INTO dw.news_items(source,source_id,data) VALUES (%s,%s,%s) "
                        "ON CONFLICT(source,source_id) DO UPDATE "
                        "SET data=EXCLUDED.data,updated_at=now()",
                        (request.source, item["source_id"], Jsonb(item)),
                    )

    def progress(self, request_id: UUID, summary: dict) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE ops.collection_requests SET summary=%s,updated_at=now() WHERE id=%s",
                (Jsonb(summary), request_id),
            )

    def save_response(
        self, request: ManagedRequest, objects: RawObjectStore, page: int, body: bytes
    ) -> None:
        response_id = uuid4()
        reference = objects.put(
            f"collection-requests/{request.id}/{response_id}.json", body, "application/json"
        )
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO st.collection_request_responses "
                "(id,request_id,page_number,metadata,raw_object) VALUES (%s,%s,%s,%s,%s)",
                (
                    response_id,
                    request.id,
                    page,
                    Jsonb({"source": request.source}),
                    Jsonb(reference.model_dump(mode="json")),
                ),
            )

    def naver_items(self, flow_run_id: UUID) -> list[dict]:
        with self.connect() as conn:
            return [
                row["data"]
                for row in conn.execute(
                    "SELECT data FROM st.search_run_items WHERE run_id=%s", (flow_run_id,)
                ).fetchall()
            ]
