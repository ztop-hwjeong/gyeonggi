from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from domain.monitoring.errors import MonitoringUnavailableError
from domain.monitoring.models import (
    ArticlePage,
    ArticleStatus,
    AttemptCount,
    CollectionError,
    CollectionMetrics,
    CollectionProgress,
    ErrorPage,
    ErrorQuery,
    HttpErrorCount,
    SearchItem,
    SearchItemPage,
    SearchMetrics,
    SearchProgress,
    SearchStream,
    SearchWindow,
    StreamPage,
    StreamQuery,
    Window,
)


class MonitoringRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _rows(self, sql: str, parameters: dict):
        try:
            return (await self._session.execute(text(sql), parameters)).mappings().all()
        except SQLAlchemyError as error:
            raise MonitoringUnavailableError("수집 저장소 조회 실패") from error

    async def progress(
        self, run_ids: list[UUID]
    ) -> dict[UUID, CollectionProgress | SearchProgress]:
        if not run_ids:
            return {}
        statement = text(
            "SELECT id, summary, 'details' AS kind FROM ops.article_detail_runs WHERE id IN :ids "
            "UNION ALL SELECT id, summary, 'search' AS kind FROM ops.search_runs WHERE id IN :ids"
        ).bindparams(bindparam("ids", expanding=True))
        try:
            rows = (await self._session.execute(statement, {"ids": run_ids})).mappings().all()
        except SQLAlchemyError as error:
            raise MonitoringUnavailableError("수집 저장소 조회 실패") from error
        return {
            row["id"]: (
                CollectionProgress.model_validate(row["summary"])
                if row["kind"] == "details"
                else SearchProgress.model_validate(row["summary"])
            )
            for row in rows
        }

    async def search_metrics(self, window: SearchWindow) -> SearchMetrics:
        params = {"since": window.since, "until": window.until, "channel": window.channel}
        condition = " AND (CAST(:channel AS text) IS NULL OR s.channel=:channel)"
        rows = await self._rows(
            "SELECT r.summary->>'status' AS status, count(*) AS count, "
            "coalesce(sum((r.summary->>'pages_collected')::int),0) AS pages, "
            "coalesce(sum((r.summary->>'retrieved_count')::int),0) AS retrieved, "
            "coalesce(sum((r.summary->>'new_count')::int),0) AS new, "
            "coalesce(sum((r.summary->>'updated_count')::int),0) AS updated "
            "FROM ops.search_runs r JOIN ops.search_streams s ON s.stream_key=r.stream_key "
            "WHERE r.created_at>=:since AND r.created_at<:until"
            + condition
            + " GROUP BY r.summary->>'status'",
            params,
        )
        raw = await self._rows(
            "SELECT count(*) AS count, coalesce(sum((a.raw_object->>'byte_length')::bigint),0) "
            "AS bytes FROM st.search_responses a JOIN ops.search_runs r ON r.id=a.run_id "
            "JOIN ops.search_streams s ON s.stream_key=r.stream_key "
            "WHERE a.created_at>=:since AND a.created_at<:until" + condition,
            params,
        )
        usage = await self._rows(
            "SELECT coalesce(sum(calls),0) AS count FROM ops.api_daily_usage "
            "WHERE provider='naver-search' AND day=(now() AT TIME ZONE 'Asia/Seoul')::date",
            {},
        )
        return SearchMetrics(
            since=window.since,
            until=window.until,
            run_status_counts={r["status"]: r["count"] for r in rows},
            pages_collected=sum(r["pages"] for r in rows),
            retrieved_count=sum(r["retrieved"] for r in rows),
            new_count=sum(r["new"] for r in rows),
            updated_count=sum(r["updated"] for r in rows),
            raw_response_count=raw[0]["count"],
            raw_response_bytes=raw[0]["bytes"],
            requests_today=usage[0]["count"],
        )

    async def streams(self, query: StreamQuery) -> StreamPage:
        condition = (
            " WHERE provider='naver' AND (CAST(:channel AS text) IS NULL OR channel=:channel)"
        )
        params = {"channel": query.channel, "limit": query.limit, "offset": query.offset}
        total = (
            await self._rows(
                "SELECT count(*) AS count FROM ops.search_streams" + condition,
                {"channel": query.channel},
            )
        )[0]["count"]
        rows = await self._rows(
            "SELECT stream_key, channel, query, cursor, "
            "(SELECT r.summary FROM ops.search_runs r WHERE r.stream_key=s.stream_key "
            "ORDER BY created_at DESC LIMIT 1) AS last_run FROM ops.search_streams s"
            + condition
            + " ORDER BY updated_at DESC, stream_key LIMIT :limit OFFSET :offset",
            params,
        )
        return StreamPage(
            items=[SearchStream.model_validate(row) for row in rows],
            total=total,
            limit=query.limit,
            offset=query.offset,
        )

    async def search_items(self, run_id: UUID, limit: int, offset: int) -> SearchItemPage:
        total = (
            await self._rows(
                "SELECT count(*) AS count FROM st.search_run_items WHERE run_id=:id",
                {"id": run_id},
            )
        )[0]["count"]
        rows = await self._rows(
            "SELECT data FROM st.search_run_items WHERE run_id=:id "
            "ORDER BY source_id LIMIT :limit OFFSET :offset",
            {"id": run_id, "limit": limit, "offset": offset},
        )
        return SearchItemPage(
            items=[SearchItem.model_validate(row["data"]) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def metrics(self, window: Window) -> CollectionMetrics:
        params = {"since": window.since, "until": window.until}
        runs = await self._rows(
            "SELECT summary->>'status' AS status, count(*) AS count, "
            "coalesce(sum((summary->>'requested_count')::int),0) AS requested "
            "FROM ops.article_detail_runs WHERE created_at >= :since AND created_at < :until "
            "GROUP BY summary->>'status'",
            params,
        )
        articles = await self._rows(
            "SELECT d.result->>'status' AS status, count(*) AS count "
            "FROM st.article_detail_results d JOIN ops.article_detail_runs r ON r.id=d.run_id "
            "WHERE r.created_at >= :since AND r.created_at < :until "
            "GROUP BY d.result->>'status'",
            params,
        )
        counts = {row["status"]: row["count"] for row in articles}
        processed = sum(counts.values())
        attempts = await self._rows(
            "SELECT a.stage, a.result->>'status' AS status, count(*) AS count "
            "FROM st.article_detail_attempts a JOIN ops.article_detail_runs r ON r.id=a.run_id "
            "WHERE r.created_at >= :since AND r.created_at < :until "
            "GROUP BY a.stage, a.result->>'status' ORDER BY a.stage, status",
            params,
        )
        responses = await self._rows(
            "SELECT count(*) AS count, coalesce(sum((raw_object->>'byte_length')::bigint),0) "
            "AS bytes FROM st.article_responses "
            "WHERE created_at >= :since AND created_at < :until",
            params,
        )
        http_errors = await self._rows(
            "SELECT stage, (metadata->>'status_code')::int AS status_code, count(*) AS count "
            "FROM st.article_responses WHERE created_at >= :since AND created_at < :until "
            "AND (metadata->>'status_code')::int >= 400 "
            "GROUP BY stage, (metadata->>'status_code')::int ORDER BY stage, status_code",
            params,
        )
        last = await self._rows(
            "SELECT max((summary->>'finished_at')::timestamptz) AS finished_at "
            "FROM ops.article_detail_runs WHERE summary->>'status'='completed'",
            {},
        )
        return CollectionMetrics(
            since=window.since,
            until=window.until,
            observed_at=datetime.now(UTC),
            run_status_counts={row["status"]: row["count"] for row in runs},
            requested_articles=sum(row["requested"] for row in runs),
            processed_articles=processed,
            collected_articles=counts.get("collected", 0),
            failed_articles=counts.get("failed", 0),
            success_rate=counts.get("collected", 0) / processed if processed else None,
            attempts=[AttemptCount.model_validate(row) for row in attempts],
            http_errors=[HttpErrorCount.model_validate(row) for row in http_errors],
            raw_response_count=responses[0]["count"],
            raw_response_bytes=responses[0]["bytes"],
            last_completed_run_at=last[0]["finished_at"],
        )

    async def errors(self, query: ErrorQuery) -> ErrorPage:
        conditions = [
            "r.created_at >= :since",
            "r.created_at < :until",
            "a.result->>'status' IN ('failed','rejected')",
        ]
        params: dict[str, object] = {"since": query.since, "until": query.until}
        if query.run_id is not None:
            conditions.append("a.run_id=:run_id")
            params["run_id"] = query.run_id
        if query.stage is not None:
            conditions.append("a.stage=:stage")
            params["stage"] = query.stage
        if query.recovered is not None:
            conditions.append("coalesce(d.result->>'status'='collected',false)=:recovered")
            params["recovered"] = query.recovered
        source = (
            " FROM st.article_detail_attempts a "
            "JOIN ops.article_detail_runs r ON r.id=a.run_id "
            "LEFT JOIN st.article_detail_results d "
            "ON d.run_id=a.run_id AND d.source_id=a.source_id WHERE " + " AND ".join(conditions)
        )
        total = (await self._rows("SELECT count(*) AS count" + source, params))[0]["count"]
        rows = await self._rows(
            "SELECT a.run_id, a.source_id, a.stage, a.result, r.created_at, "
            "coalesce(d.result->>'status'='collected',false) AS recovered"
            + source
            + " ORDER BY r.created_at DESC, a.run_id, a.source_id, a.stage "
            "LIMIT :limit OFFSET :offset",
            {**params, "limit": query.limit, "offset": query.offset},
        )
        return ErrorPage(
            total=total,
            limit=query.limit,
            offset=query.offset,
            items=[
                CollectionError(
                    run_id=row["run_id"],
                    source_id=row["source_id"],
                    stage=row["stage"],
                    status=row["result"]["status"],
                    reason=row["result"]["reason"],
                    recovered=row["recovered"],
                    run_created_at=row["created_at"],
                    http_status_codes=[s["status_code"] for s in row["result"]["snapshots"]],
                )
                for row in rows
            ],
        )

    async def articles(self, run_id: UUID, limit: int, offset: int) -> ArticlePage:
        params = {"run_id": run_id}
        total = (
            await self._rows(
                "SELECT count(*) AS count FROM st.article_detail_results WHERE run_id=:run_id",
                params,
            )
        )[0]["count"]
        rows = await self._rows(
            "SELECT source_id, result->'seed'->>'publisher' AS publisher, "
            "result->'seed'->>'title' AS title, result->>'status' AS status, "
            "result->>'selected_stage' AS selected_stage "
            "FROM st.article_detail_results WHERE run_id=:run_id "
            "ORDER BY source_id LIMIT :limit OFFSET :offset",
            {**params, "limit": limit, "offset": offset},
        )
        return ArticlePage(
            items=[ArticleStatus.model_validate(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )
