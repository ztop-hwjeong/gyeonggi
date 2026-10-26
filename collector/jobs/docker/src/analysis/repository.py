from uuid import UUID, uuid4

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from analysis.client import MODEL, PROMPT, PROMPT_HASH
from analysis.models import Article, Topic
from analysis.tables import article_contents, attempts, queue, runs, topics


class AnalysisRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def article(self, source: str, source_id: str, content_hash: str) -> Article | None:
        async with self.sessions() as session:
            row = (
                (
                    await session.execute(
                        select(
                            article_contents.c.material_id.label("article_id"),
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

    async def topics(self) -> list[Topic]:
        async with self.sessions() as session:
            rows = (
                (
                    await session.execute(
                        select(topics.c.id, topics.c.name, topics.c.description, topics.c.synonyms)
                        .where(topics.c.merged_into.is_(None), topics.c.archived_at.is_(None))
                        .order_by(topics.c.name)
                    )
                )
                .mappings()
                .all()
            )
        return [Topic.model_validate(row) for row in rows]

    async def claim(
        self,
        article: Article,
        catalog: list[Topic],
        flow_run_id: UUID | None,
        task_run_id: UUID | None,
    ) -> tuple[UUID, int]:
        run_id = uuid4()
        snapshot = {
            "topics": [
                {"id": topic.id, "name": topic.name, "description": topic.description}
                for topic in catalog
            ]
        }
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
                    catalog_snapshot=snapshot,
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
