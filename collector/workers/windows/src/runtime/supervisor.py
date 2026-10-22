import argparse
import asyncio
import logging
import sys

from playwright.async_api import Error

from browser.connection import launch_edge
from config import EdgeSettings, RuntimeSettings, WorkerSettings
from runtime.process import subprocess_environment
from runtime.state import RuntimeIdentity


async def maintain_edge(settings: EdgeSettings) -> None:
    while True:
        try:
            async with launch_edge(settings) as context:
                closed = asyncio.Event()
                context.on("close", lambda _, event=closed: event.set())
                await closed.wait()
        except (Error, OSError):
            logging.getLogger(__name__).exception("Edge 실행 실패")
        logging.getLogger(__name__).warning(
            "Edge 창 종료 감지: %s초 후 다시 실행", settings.browser_restart_delay
        )
        await asyncio.sleep(settings.browser_restart_delay)


async def maintain_worker(
    worker: WorkerSettings, identity: RuntimeIdentity, environment: dict[str, str]
) -> None:
    while True:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "prefect",
            "worker",
            "start",
            "--pool",
            worker.worker_pool,
            "--type",
            "process",
            "--name",
            identity.name,
            "--limit",
            str(worker.worker_limit),
            cwd=worker.collector_directory,
            env=environment,
        )
        try:
            exit_code = await process.wait()
        finally:
            if process.returncode is None:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=worker.process_stop_timeout)
        logging.getLogger(__name__).warning(
            "Worker 종료(%s): %s초 후 다시 실행", exit_code, worker.worker_restart_delay
        )
        await asyncio.sleep(worker.worker_restart_delay)


async def supervise(settings: RuntimeSettings, identity: RuntimeIdentity) -> None:
    async with asyncio.TaskGroup() as tasks:
        tasks.create_task(maintain_edge(settings.edge))
        tasks.create_task(
            maintain_worker(settings.worker, identity, subprocess_environment(settings))
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--service", required=True)
    args = parser.parse_args()
    identity = RuntimeIdentity(project=args.project_name, service=args.service)
    asyncio.run(supervise(RuntimeSettings.load({}), identity))


if __name__ == "__main__":
    main()
