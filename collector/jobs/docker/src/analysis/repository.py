from uuid import UUID, uuid4

from sqlalchemy import func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from analysis.client import MODEL, PROMPT, PROMPT_HASH
from analysis.models import Article
from analysis.reprints import MATCHING_BASIS, ReprintCandidate, ReprintMatch
from analysis.tables import article_contents, articles, attempts, queue, reprints, runs


class AnalysisRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def article(self, source: str, source_id: str, content_hash: str) -> Article | None:
        async with self.sessions() as session:
            row = (
                (
                    await session.execute(
                        select(
                            article_contents.c.article_id,
                            article_contents.c.source,
                            article_contents.c.source_id,
                            article_contents.c.content_hash,
                            article_contents.c.title,
                            article_contents.c.body,
                        ).where(
                            article_contents.c.source == source,
                            article_contents.c.source_id == source_id,
                            article_contents.c.content_hash == content_hash,
                        )
                    )
                )
                .mappings()
                .first()
            )
        return Article.model_validate(row) if row else None

    async def reprint_candidates(
        self, article_id: UUID
    ) -> tuple[str | None, list[ReprintCandidate]]:
        latest = select(
            article_contents.c.article_id,
            article_contents.c.content_hash,
            article_contents.c.body,
            func.row_number()
            .over(
                partition_by=article_contents.c.article_id,
                order_by=(article_contents.c.created_at.desc(), article_contents.c.id.desc()),
            )
            .label("position"),
        ).subquery()
        async with self.sessions() as session:
            publisher = (
                await session.execute(
                    select(articles.c.publisher).where(articles.c.id == article_id)
                )
            ).scalar_one_or_none()
            if not publisher:
                return None, []
            rows = (
                (
                    await session.execute(
                        select(
                            latest.c.article_id,
                            latest.c.content_hash,
                            latest.c.body,
                            articles.c.publisher,
                        )
                        .join(articles, articles.c.id == latest.c.article_id)
                        .where(latest.c.position == 1, latest.c.article_id != article_id)
                    )
                )
                .mappings()
                .all()
            )
        return publisher, [
            ReprintCandidate(row.article_id, row.content_hash, row.body, row.publisher)
            for row in rows
        ]

    async def save_reprints(self, article: Article, matches: list[ReprintMatch]) -> None:
        if not matches:
            return
        async with self.sessions() as session, session.begin():
            for match in matches:
                first = article.article_id < match.article_id
                values = {
                    "article_a_id": article.article_id if first else match.article_id,
                    "article_b_id": match.article_id if first else article.article_id,
                    "article_a_content_hash": article.content_hash if first else match.content_hash,
                    "article_b_content_hash": match.content_hash if first else article.content_hash,
                    "body_similarity": match.similarity,
                    "matching_basis": MATCHING_BASIS,
                }
                await session.execute(
                    pg_insert(reprints)
                    .values(**values)
                    .on_conflict_do_update(
                        index_elements=(
                            reprints.c.article_a_id,
                            reprints.c.article_b_id,
                            reprints.c.article_a_content_hash,
                            reprints.c.article_b_content_hash,
                        ),
                        set_={"body_similarity": match.similarity, "checked_at": func.now()},
                    )
                )

    async def claim(
        self,
        article: Article,
        flow_run_id: UUID | None,
        task_run_id: UUID | None,
    ) -> tuple[UUID, int]:
        run_id = uuid4()
        async with self.sessions() as session, session.begin():
            await session.execute(
                insert(runs).values(
                    id=run_id,
                    article_id=article.article_id,
                    source=article.source,
                    source_id=article.source_id,
                    content_hash=article.content_hash,
                    model=MODEL,
                    prompt=PROMPT,
                    prompt_hash=PROMPT_HASH,
                    status="running",
                )
            )
            await self._queue_status(session, article.article_id, article.content_hash, "running")
            attempt_id = (
                await session.execute(
                    insert(attempts)
                    .values(
                        run_id=run_id,
                        prefect_flow_run_id=flow_run_id,
                        prefect_task_run_id=task_run_id,
                        status="running",
                        model=MODEL,
                        prompt=PROMPT,
                        prompt_hash=PROMPT_HASH,
                    )
                    .returning(attempts.c.id)
                )
            ).scalar_one()
        return run_id, attempt_id

    async def complete(self, run_id: UUID, attempt_id: int, draft: dict, usage: dict) -> None:
        async with self.sessions() as session, session.begin():
            row = (
                await session.execute(
                    update(runs)
                    .where(runs.c.id == run_id)
                    .values(
                        status="completed",
                        model_draft=draft,
                        usage=usage,
                        error=None,
                        lease_expires_at=None,
                        updated_at=func.now(),
                    )
                    .returning(runs.c.article_id, runs.c.content_hash)
                )
            ).first()
            if row is not None:
                await self._queue_status(session, row.article_id, row.content_hash, "completed")
            await session.execute(
                update(attempts)
                .where(attempts.c.id == attempt_id)
                .values(
                    status="completed",
                    model_draft=draft,
                    usage=usage,
                    finished_at=func.now(),
                )
            )

    async def fail(self, run_id: UUID, attempt_id: int, error: Exception) -> None:
        name = type(error).__name__
        async with self.sessions() as session, session.begin():
            row = (
                await session.execute(
                    update(runs)
                    .where(runs.c.id == run_id)
                    .values(
                        status="failed",
                        error=name,
                        lease_expires_at=None,
                        updated_at=func.now(),
                    )
                    .returning(runs.c.article_id, runs.c.content_hash)
                )
            ).first()
            if row is not None:
                await self._queue_status(session, row.article_id, row.content_hash, "failed")
            await session.execute(
                update(attempts)
                .where(attempts.c.id == attempt_id)
                .values(
                    status="failed",
                    error=name,
                    finished_at=func.now(),
                )
            )

    @staticmethod
    async def _queue_status(
        session: AsyncSession, article_id: UUID, content_hash: str, status: str
    ) -> None:
        await session.execute(
            update(queue)
            .where(
                queue.c.article_id == article_id,
                queue.c.content_hash == content_hash,
                queue.c.status != "completed",
            )
            .values(status=status, updated_at=func.now())
        )
