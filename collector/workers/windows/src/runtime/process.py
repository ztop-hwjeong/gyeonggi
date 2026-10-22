import os
import subprocess
import sys

import psutil

from config import RuntimeSettings
from runtime.state import ProcessState, ProcessStateStore, RuntimeIdentity


def subprocess_environment(settings: RuntimeSettings) -> dict[str, str]:
    worker, edge = settings.worker, settings.edge
    browser, recovery = settings.browser, settings.recovery
    return {
        **os.environ,
        "COLLECTOR_DIRECTORY": str(worker.collector_directory),
        "RUNTIME_DIRECTORY": str(worker.runtime_directory),
        "PREFECT_API_URL": str(worker.prefect_api_url),
        "WORKER_POOL": worker.worker_pool,
        "WORKER_LIMIT": str(worker.worker_limit),
        "WORKER_RESTART_DELAY": str(worker.worker_restart_delay),
        "PROCESS_STOP_TIMEOUT": str(worker.process_stop_timeout),
        "BROWSER_PROFILE_DIRECTORY": str(edge.browser_profile_directory),
        "EDGE_DEFAULT_PROFILE_DIRECTORY": str(edge.edge_default_profile_directory),
        "BROWSER_CDP_URL": str(edge.browser_cdp_url),
        "BROWSER_RESTART_DELAY": str(edge.browser_restart_delay),
        "BROWSER_LAUNCH_TIMEOUT_MS": str(edge.browser_launch_timeout_ms),
        "BROWSER_CONNECT_TIMEOUT_MS": str(browser.browser_connect_timeout_ms),
        "BROWSER_NAVIGATION_TIMEOUT_MS": str(browser.browser_navigation_timeout_ms),
        "BROWSER_OPERATION_ATTEMPTS": str(recovery.browser_operation_attempts),
        "BROWSER_OPERATION_RETRY_DELAY": str(recovery.browser_operation_retry_delay),
        "PYTHONPATH": str(worker.collector_directory / "src"),
        "DO_NOT_TRACK": "1",
        "PYTHONUNBUFFERED": "1",
    }


def running_process(store: ProcessStateStore) -> psutil.Process | None:
    state = store.load()
    if state is None:
        return None
    try:
        process = psutil.Process(state.pid)
        # PID 재사용 시 다른 프로세스 종료 방지를 위한 생성 시각 비교
        if process.create_time() == state.started_at:
            return process
    except psutil.NoSuchProcess:
        return None
    return None


def start_supervisor(
    settings: RuntimeSettings, identity: RuntimeIdentity, store: ProcessStateStore
) -> None:
    if running_process(store) is not None:
        return
    store.path.parent.mkdir(parents=True, exist_ok=True)
    with store.path.with_suffix(".log").open("ab") as log:
        child = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "runtime.supervisor",
                "--project-name",
                identity.project,
                "--service",
                identity.service,
            ],
            cwd=settings.worker.collector_directory,
            env=subprocess_environment(settings),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    process = psutil.Process(child.pid)
    store.save(ProcessState(pid=child.pid, started_at=process.create_time()))


def stop_supervisor(store: ProcessStateStore, timeout: float) -> None:
    process = running_process(store)
    if process is not None:
        try:
            descendants = process.children(recursive=True)
            targets = [process, *descendants]
            for target in targets:
                try:
                    target.kill()
                except psutil.NoSuchProcess:
                    pass
            _, alive = psutil.wait_procs(targets, timeout=timeout)
            if alive:
                raise TimeoutError("Windows 수집 프로세스 종료 시간 초과")
        except psutil.NoSuchProcess:
            pass
    store.clear()
