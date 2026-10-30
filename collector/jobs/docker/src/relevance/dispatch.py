from datetime import UTC, datetime, timedelta

from prefect.client.orchestration import SyncPrefectClient
from prefect.exceptions import ObjectNotFound
from sqlalchemy import select, update

from relevance.repository import RelevanceRepository
from relevance.tables import report_relevance_runs


async def recover_expired(repository: RelevanceRepository, client: SyncPrefectClient) -> None:
    async with repository.sessions() as session, session.begin():
        rows = (
            (
                await session.execute(
                    select(
                        report_relevance_runs.c.id,
                        report_relevance_runs.c.status,
                        report_relevance_runs.c.flow_run_id,
                    )
                    .where(
                        report_relevance_runs.c.status.in_(("submitted", "running")),
                        report_relevance_runs.c.lease_expires_at < datetime.now(UTC),
                    )
                    .with_for_update(skip_locked=True)
                )
            )
            .mappings()
            .all()
        )
        for row in rows:
            if row["status"] == "running" or row["flow_run_id"] is None:
                await session.execute(
                    update(report_relevance_runs)
                    .where(report_relevance_runs.c.id == row["id"])
                    .values(status="failed", error="lease_expired", lease_expires_at=None)
                )
                continue
            try:
                state = client.read_flow_run(row["flow_run_id"]).state
            except ObjectNotFound:
                await session.execute(
                    update(report_relevance_runs)
                    .where(report_relevance_runs.c.id == row["id"])
                    .values(status="failed", error="flow_not_found", lease_expires_at=None)
                )
                continue
            except Exception:
                continue
            if state and state.is_final():
                await session.execute(
                    update(report_relevance_runs)
                    .where(report_relevance_runs.c.id == row["id"])
                    .values(
                        status="failed",
                        error=f"flow_{state.type.value.lower()}",
                        lease_expires_at=None,
                    )
                )
            else:
                await session.execute(
                    update(report_relevance_runs)
                    .where(report_relevance_runs.c.id == row["id"])
                    .values(lease_expires_at=datetime.now(UTC) + timedelta(minutes=20))
                )


async def dispatch_one(
    repository: RelevanceRepository, client: SyncPrefectClient, deployment: str
) -> bool:
    async with repository.sessions() as session, session.begin():
        row = (
            (
                await session.execute(
                    select(report_relevance_runs.c.id, report_relevance_runs.c.submission_attempts)
                    .where(report_relevance_runs.c.status == "queued")
                    .order_by(report_relevance_runs.c.created_at, report_relevance_runs.c.id)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return False
        try:
            target = client.read_deployment_by_name(deployment)
            run = client.create_flow_run_from_deployment(
                target.id,
                parameters={"run_id": str(row["id"])},
                idempotency_key=f"report-relevance:{row['id']}:{row['submission_attempts']}",
            )
        except Exception as error:
            await session.execute(
                update(report_relevance_runs)
                .where(report_relevance_runs.c.id == row["id"])
                .values(
                    status="failed",
                    error=f"submission_{type(error).__name__}",
                    updated_at=datetime.now(UTC),
                )
            )
            return True
        await session.execute(
            update(report_relevance_runs)
            .where(report_relevance_runs.c.id == row["id"])
            .values(
                status="submitted",
                flow_run_id=run.id,
                submission_attempts=row["submission_attempts"] + 1,
                lease_expires_at=datetime.now(UTC) + timedelta(minutes=20),
                updated_at=datetime.now(UTC),
                error=None,
            )
        )
        return True
