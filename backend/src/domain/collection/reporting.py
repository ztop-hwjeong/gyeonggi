from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from domain.collection.errors import CollectionUnavailableError
from domain.collection.models import ArticleQuery, Overview, StoredArticle, StoredArticlePage


class CollectionReporting:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def rows(self, sql: str, parameters: dict | None = None):
        try:
            return (await self._session.execute(text(sql), parameters or {})).mappings().all()
        except SQLAlchemyError as error:
            raise CollectionUnavailableError("수집 결과 저장소 연결 실패") from error

    def items_sql(self) -> str:
        return (
            "SELECT source,source_id,data,first_seen_at FROM dw.news_items UNION ALL "
            "SELECT 'naver_'||channel AS source,source_id,data,first_seen_at FROM dw.search_items"
        )

    async def overview(self) -> Overview:
        sources = await self.rows(
            "SELECT source,count(*) AS count FROM (" + self.items_sql() + ") items GROUP BY source"
        )
        counts = await self.rows(
            "SELECT (SELECT count(*) FROM ops.collection_rules "
            "WHERE definition->>'enabled'='true') AS active_rules, "
            "count(*) FILTER (WHERE status IN ('queued','submitted','running','cancelling')) "
            "AS queued_requests, count(*) FILTER (WHERE status='failed' "
            "AND created_at>=now()-interval '24 hours') AS failed_requests "
            "FROM ops.collection_requests"
        )
        days = await self.rows(
            "WITH items AS (" + self.items_sql() + "), daily AS ("
            "SELECT (first_seen_at AT TIME ZONE 'Asia/Seoul')::date AS day,count(*) AS count "
            "FROM items WHERE first_seen_at>=now()-interval '7 days' GROUP BY 1) "
            "SELECT day::date,coalesce(daily.count,0) AS count FROM generate_series("
            "(now() AT TIME ZONE 'Asia/Seoul')::date-6,"
            "(now() AT TIME ZONE 'Asia/Seoul')::date,interval '1 day') AS days(day) "
            "LEFT JOIN daily USING(day) ORDER BY day"
        )
        return Overview.model_validate(
            {
                **counts[0],
                "total_items": sum(row["count"] for row in sources),
                "source_counts": {row["source"]: row["count"] for row in sources},
                "daily_counts": days,
            }
        )

    async def articles(self, query: ArticleQuery) -> StoredArticlePage:
        criteria = (
            " WHERE (CAST(:source AS text) IS NULL OR i.source=:source) "
            "AND (:q='' OR i.data->>'title' ILIKE :pattern OR i.data->>'summary' ILIKE :pattern)"
        )
        params = {
            **query.model_dump(),
            "pattern": "%"
            + query.q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            + "%",
        }
        base = "(" + self.items_sql() + ") i"
        total = (await self.rows("SELECT count(*) AS count FROM " + base + criteria, params))[0][
            "count"
        ]
        rows = await self.rows(
            "SELECT i.source,i.source_id,i.data,i.first_seen_at,EXISTS("
            "SELECT 1 FROM dw.article_contents c "
            "WHERE c.source=i.source AND c.source_id=i.source_id"
            ") AS has_body FROM "
            + base
            + criteria
            + " ORDER BY i.first_seen_at DESC,i.source,i.source_id LIMIT :limit OFFSET :offset",
            params,
        )
        return StoredArticlePage(
            items=[StoredArticle.model_validate({**row["data"], **row}) for row in rows],
            total=total,
        )
