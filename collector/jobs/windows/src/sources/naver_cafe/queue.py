from collections.abc import Generator
from contextlib import contextmanager

from articles.models import ArticleSeed
from articles.storage import DetailRepository
from sources.naver_cafe.models import CafeSettings


class CafeQueue:
    def __init__(self, repository: DetailRepository, settings: CafeSettings) -> None:
        self.repository = repository
        self.settings = settings

    @contextmanager
    def batch(self) -> Generator[list[ArticleSeed]]:
        with self.repository.connect() as connection:
            connection.autocommit = True
            locked = connection.execute(
                "SELECT pg_try_advisory_lock(hashtextextended('naver-cafe-details',0))"
            ).fetchone()
            if not locked or not locked[0]:
                raise RuntimeError("카페 상세 수집이 이미 실행 중")
            try:
                if connection.execute(
                    "SELECT 1 FROM ops.api_request_pauses "
                    "WHERE provider='naver-cafe-detail' AND retry_at>now()"
                ).fetchone():
                    raise RuntimeError("카페 상세 요청 대기 시간 유지")
                rows = connection.execute(
                    "SELECT i.source_id,i.data FROM dw.search_items i "
                    "WHERE i.provider='naver' AND i.channel='cafearticle' "
                    "AND NOT EXISTS (SELECT 1 FROM dw.article_contents c "
                    "WHERE c.source='naver_cafearticle' AND c.source_id=i.source_id) "
                    "AND NOT EXISTS (SELECT 1 FROM st.article_detail_results r "
                    "JOIN ops.article_detail_runs run ON run.id=r.run_id "
                    "WHERE r.source_id=i.source_id "
                    "AND r.result->'seed'->>'source'='naver_cafearticle' "
                    "AND run.created_at>now()-%s*interval '1 minute') "
                    "ORDER BY i.first_seen_at,i.source_id LIMIT %s",
                    (self.settings.retry_delay_minutes, self.settings.batch_size),
                ).fetchall()
                yield [
                    ArticleSeed(
                        source="naver_cafearticle",
                        source_id=source_id,
                        published_on=None,
                        publisher=data.get("container_name") or "네이버 카페",
                        title=data["title"],
                        original_url=data["url"],
                        summary=data["summary"],
                    )
                    for source_id, data in rows
                ]
            finally:
                connection.execute(
                    "SELECT pg_advisory_unlock(hashtextextended('naver-cafe-details',0))"
                )

    def pause(self, seconds: float) -> None:
        with self.repository.connect() as connection:
            connection.execute(
                "INSERT INTO ops.api_request_pauses(provider,retry_at) "
                "VALUES ('naver-cafe-detail',now()+%s*interval '1 second') "
                "ON CONFLICT(provider) DO UPDATE SET retry_at="
                "GREATEST(ops.api_request_pauses.retry_at,EXCLUDED.retry_at)",
                (seconds,),
            )
