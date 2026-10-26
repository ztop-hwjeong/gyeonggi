from hashlib import sha256

from prefect.client.orchestration import SyncPrefectClient
from sqlalchemy import and_, func, select, update

from analysis.client import MODEL, PROMPT_HASH
from analysis.repository import AnalysisRepository
from analysis.tables import queue, queue_keys


async def dispatch_one(
    repository: AnalysisRepository, client: SyncPrefectClient, deployment_name: str
) -> bool:
    async with repository.sessions() as session, session.begin():
        row = (
            (
                await session.execute(
                    select(
                        queue.c.article_id, queue.c.source, queue.c.source_id, queue.c.content_hash
                    )
                    .join(
                        queue_keys,
                        and_(
                            queue_keys.c.article_id == queue.c.article_id,
                            queue_keys.c.content_hash == queue.c.content_hash,
                            queue_keys.c.source == queue.c.source,
                            queue_keys.c.source_id == queue.c.source_id,
                        ),
                    )
                    .where(
                        queue.c.status == "queued", queue.c.source.in_(("bigkinds", "naver_news"))
                    )
                    .order_by(queue.c.created_at)
                    .limit(1)
                    .with_for_update(of=queue, skip_locked=True)
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return False
        deployment = client.read_deployment_by_name(deployment_name)
        fingerprint = sha256(
            "\x00".join((str(row["article_id"]), row["content_hash"], MODEL, PROMPT_HASH)).encode()
        ).hexdigest()
        run = client.create_flow_run_from_deployment(
            deployment.id,
            parameters={
                "source": row["source"],
                "source_id": row["source_id"],
                "content_hash": row["content_hash"],
            },
            idempotency_key=f"analysis:{fingerprint}",
        )
        await session.execute(
            update(queue)
            .where(
                queue.c.article_id == row["article_id"],
                queue.c.content_hash == row["content_hash"],
                queue.c.status == "queued",
            )
            .values(status="submitted", flow_run_id=run.id, error=None, updated_at=func.now())
        )
        return True
