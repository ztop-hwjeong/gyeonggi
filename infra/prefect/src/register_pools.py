import asyncio

from prefect.client.orchestration import get_client
from prefect.client.schemas.actions import GlobalConcurrencyLimitCreate, WorkPoolCreate
from prefect.exceptions import ObjectNotFound
from prefect.workers.base import BaseWorker
from prefect.workers.process import ProcessWorker
from prefect_docker.worker import DockerWorker

from config import BigKindsRateLimitSettings


async def register_pools() -> None:
    pools: tuple[tuple[str, type[BaseWorker]], ...] = (
        ("docker-collector", DockerWorker),
        ("windows-collector", ProcessWorker),
    )
    async with get_client() as client:
        for name, worker_type in pools:
            try:
                pool = await client.read_work_pool(name)
            except ObjectNotFound:
                await client.create_work_pool(
                    WorkPoolCreate(
                        name=name,
                        type=worker_type.type,
                        base_job_template=worker_type.get_default_base_job_template(),
                    )
                )
            else:
                if pool.type != worker_type.type:
                    raise RuntimeError(f"{name} pool의 타입 불일치: {pool.type}")
        settings = BigKindsRateLimitSettings()
        try:
            await client.read_global_concurrency_limit_by_name(settings.rate_limit_name)
        except ObjectNotFound:
            await client.create_global_concurrency_limit(
                GlobalConcurrencyLimitCreate(
                    name=settings.rate_limit_name,
                    limit=1,
                    slot_decay_per_second=1 / settings.request_interval_seconds,
                )
            )


if __name__ == "__main__":
    asyncio.run(register_pools())
