from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import psycopg
from collector_storage.config import DatabaseSettings
from collector_storage.objects import RawObjectStore
from psycopg.types.json import Jsonb
from pydantic import SecretStr

from sources.naver.models import Cursor, Listing, SearchRequest, SearchSummary


class RequestBudgetExceeded(RuntimeError):
    pass


class RequestsPaused(RuntimeError):
    pass


class SearchRepository:
    def __init__(self, settings: DatabaseSettings, password: SecretStr) -> None:
        self.settings = settings
        self.password = password

    def connect(self) -> psycopg.Connection:
        return psycopg.connect(
            host=self.settings.database_host,
            port=self.settings.database_port,
            dbname=self.settings.database_name,
            user=self.settings.database_user,
            password=self.password.get_secret_value(),
            autocommit=True,
            connect_timeout=5,
            options="-c statement_timeout=5000",
        )

    @contextmanager
    def lock(self, request: SearchRequest) -> Generator[psycopg.Connection]:
        lock_key = int.from_bytes(bytes.fromhex(request.stream_key)[:8], signed=True)
        with self.connect() as connection:
            row = connection.execute("SELECT pg_try_advisory_lock(%s)", (lock_key,)).fetchone()
            if row is None or not row[0]:
                raise RuntimeError("같은 검색 스트림 수집이 이미 실행 중")
            try:
                connection.execute(
                    "INSERT INTO ops.search_streams(stream_key,provider,channel,query) "
                    "VALUES (%s,'naver',%s,%s) ON CONFLICT DO NOTHING",
                    (request.stream_key, request.channel, request.query),
                )
                yield connection
            finally:
                connection.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))

    def cursor(self, connection: psycopg.Connection, key: str) -> Cursor | None:
        row = connection.execute(
            "SELECT cursor FROM ops.search_streams WHERE stream_key=%s", (key,)
        ).fetchone()
        return Cursor.model_validate(row[0]) if row and row[0] is not None else None

    def save_run(self, connection: psycopg.Connection, summary: SearchSummary) -> None:
        connection.execute(
            "INSERT INTO ops.search_runs(id,stream_key,summary) VALUES (%s,%s,%s) "
            "ON CONFLICT(id) DO UPDATE SET summary=EXCLUDED.summary",
            (summary.run_id, summary.stream_key, Jsonb(summary.model_dump(mode="json"))),
        )

    def reserve_request(self, daily_limit: int) -> None:
        with self.connect() as connection:
            paused = connection.execute(
                "SELECT 1 FROM ops.api_request_pauses WHERE provider='naver-search' "
                "AND retry_at>now()"
            ).fetchone()
            if paused:
                raise RequestsPaused("네이버 API의 요청 대기 시간 유지")
            row = connection.execute(
                "INSERT INTO ops.api_daily_usage(provider,day,calls) VALUES ('naver-search',%s,1) "
                "ON CONFLICT(provider,day) DO UPDATE SET calls=ops.api_daily_usage.calls+1 "
                "WHERE ops.api_daily_usage.calls < %s RETURNING calls",
                (datetime.now(ZoneInfo("Asia/Seoul")).date(), daily_limit),
            ).fetchone()
        if row is None:
            raise RequestBudgetExceeded("네이버 검색 일일 요청 예산 소진")

    def pause_requests(self, seconds: float) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO ops.api_request_pauses(provider,retry_at) "
                "VALUES ('naver-search',now()+%s*interval '1 second') ON CONFLICT(provider) "
                "DO UPDATE SET retry_at="
                "GREATEST(ops.api_request_pauses.retry_at,EXCLUDED.retry_at)",
                (seconds,),
            )

    def save_response(
        self,
        connection: psycopg.Connection,
        objects: RawObjectStore,
        summary: SearchSummary,
        start: int,
        status: int,
        content_type: str,
        body: bytes,
    ) -> UUID:
        response_id = uuid4()
        reference = objects.put(f"naver/{summary.run_id}/{response_id}", body, content_type)
        connection.execute(
            "INSERT INTO st.search_responses(id,run_id,start_position,status_code,metadata,"
            "raw_object) VALUES (%s,%s,%s,%s,%s,%s)",
            (
                response_id,
                summary.run_id,
                start,
                status,
                Jsonb({"received_at": datetime.now(UTC).isoformat(), "content_type": content_type}),
                Jsonb(reference.model_dump(mode="json")),
            ),
        )
        return response_id

    def save_items(
        self,
        connection: psycopg.Connection,
        summary: SearchSummary,
        response_id: UUID,
        items: list[Listing],
    ) -> tuple[int, int]:
        new_count = updated_count = 0
        with connection.transaction():
            for item in items:
                data = item.model_dump(mode="json")
                digest = sha256(item.model_dump_json().encode()).hexdigest()
                inserted_item = connection.execute(
                    "INSERT INTO dw.search_items(provider,channel,source_id,content_hash,data) "
                    "VALUES ('naver',%s,%s,%s,%s) ON CONFLICT(provider,channel,source_id) "
                    "DO NOTHING RETURNING 1",
                    (item.channel, item.source_id, digest, Jsonb(data)),
                ).fetchone()
                is_new, is_updated = inserted_item is not None, False
                if not is_new:
                    row = connection.execute(
                        "SELECT content_hash FROM dw.search_items "
                        "WHERE provider='naver' AND channel=%s AND source_id=%s FOR UPDATE",
                        (item.channel, item.source_id),
                    ).fetchone()
                    if row is None:
                        raise RuntimeError("검색 항목 갱신 중 원본 항목 없음")
                    is_updated = row[0] != digest
                    connection.execute(
                        "UPDATE dw.search_items SET data=%s,content_hash=%s,last_seen_at=now() "
                        "WHERE provider='naver' AND channel=%s AND source_id=%s",
                        (Jsonb(data), digest, item.channel, item.source_id),
                    )
                inserted = connection.execute(
                    "INSERT INTO st.search_run_items(run_id,source_id,response_id,data,is_new,"
                    "is_updated) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING 1",
                    (summary.run_id, item.source_id, response_id, Jsonb(data), is_new, is_updated),
                ).fetchone()
                if inserted:
                    new_count += int(is_new)
                    updated_count += int(is_updated)
        return new_count, updated_count

    def finish(
        self, connection: psycopg.Connection, summary: SearchSummary, cursor: Cursor | None
    ) -> None:
        with connection.transaction():
            self.save_run(connection, summary)
            if summary.cursor_advanced:
                if cursor is None:
                    raise ValueError("갱신할 검색 커서 없음")
                connection.execute(
                    "UPDATE ops.search_streams SET cursor=%s,updated_at=now() WHERE stream_key=%s",
                    (Jsonb(cursor.model_dump(mode="json")), summary.stream_key),
                )
