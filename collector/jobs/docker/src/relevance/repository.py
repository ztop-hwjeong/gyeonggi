from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from relevance.client import MODEL, prompt_for
from relevance.models import RelevanceInput
from relevance.tables import article_contents, report_relevance_runs


class RelevanceRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def claim(self, run_id: UUID, flow_run_id: UUID | None) -> RelevanceInput | None:
        async with self.sessions() as session, session.begin():
            row = (
                (
                    await session.execute(
                        update(report_relevance_runs)
                        .where(
                            report_relevance_runs.c.id == run_id,
                            report_relevance_runs.c.status.in_(("queued", "submitted")),
                        )
                        .values(
                            status="running",
                            flow_run_id=flow_run_id,
                            lease_expires_at=datetime.now(UTC) + timedelta(minutes=20),
                            updated_at=func.now(),
                        )
                        .returning(report_relevance_runs)
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            body = (
                await session.execute(
                    select(article_contents.c.body).where(
                        article_contents.c.id == row["content_id"]
                    )
                )
            ).scalar_one_or_none()
            if body is None:
                await session.execute(
                    update(report_relevance_runs)
                    .where(
                        report_relevance_runs.c.id == run_id,
                        report_relevance_runs.c.status == "running",
                    )
                    .values(status="failed", error="missing_content", lease_expires_at=None)
                )
                return None
            prompt = prompt_for(row["criteria"])
            await session.execute(
                update(report_relevance_runs)
                .where(report_relevance_runs.c.id == run_id)
                .values(
                    model=MODEL,
                    prompt=prompt,
                    prompt_hash=sha256(prompt.encode("utf-8")).hexdigest(),
                )
            )
            return RelevanceInput(
                run_id=run_id, title=row["title"], body=body, criteria=row["criteria"]
            )

    async def complete(self, item: RelevanceInput, draft: dict, usage: dict) -> None:
        evidence = draft["evidence"]
        if draft["relevance"] in ("related", "unrelated") and not evidence:
            raise ValueError("관련성 판정 근거 필요")
        if any(quote not in item.title and quote not in item.body for quote in evidence):
            raise ValueError("근거 인용 원문 불일치")
        prompt = prompt_for(item.criteria)
        async with self.sessions() as session, session.begin():
            result = await session.execute(
                update(report_relevance_runs)
                .where(
                    report_relevance_runs.c.id == item.run_id,
                    report_relevance_runs.c.status == "running",
                )
                .values(
                    status="completed",
                    model=MODEL,
                    prompt=prompt,
                    prompt_hash=sha256(prompt.encode("utf-8")).hexdigest(),
                    relevance=draft["relevance"],
                    reason=draft["reason"],
                    evidence=evidence,
                    usage=usage,
                    error=None,
                    lease_expires_at=None,
                    updated_at=func.now(),
                )
                .returning(report_relevance_runs.c.id)
            )
            if result.scalar_one_or_none() is None:
                raise RuntimeError("관련성 실행 소유권 만료")

    async def fail(self, run_id: UUID, error: Exception) -> None:
        async with self.sessions() as session, session.begin():
            await session.execute(
                update(report_relevance_runs)
                .where(
                    report_relevance_runs.c.id == run_id,
                    report_relevance_runs.c.status == "running",
                )
                .values(
                    status="failed",
                    error=type(error).__name__,
                    lease_expires_at=None,
                    updated_at=func.now(),
                )
            )
