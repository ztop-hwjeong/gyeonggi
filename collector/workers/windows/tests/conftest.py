from pathlib import Path

import pytest

from config import RuntimeSettings


@pytest.fixture
def runtime_settings(tmp_path: Path) -> RuntimeSettings:
    return RuntimeSettings.load(
        {
            "collector_directory": tmp_path,
            "runtime_directory": tmp_path / "runtime",
            "browser_profile_directory": tmp_path / "collector-profile",
            "edge_default_profile_directory": tmp_path / "edge-default",
            "prefect_api_url": "http://127.0.0.1:4200/api",
            "browser_cdp_url": "http://127.0.0.1:9222",
            "worker_pool": "windows-collector",
            "worker_limit": 1,
            "worker_restart_delay": 10,
            "process_stop_timeout": 5,
            "browser_restart_delay": 3,
            "browser_operation_attempts": 3,
            "browser_operation_retry_delay": 0.001,
            "browser_connect_timeout_ms": 5_000,
            "browser_launch_timeout_ms": 30_000,
            "browser_navigation_timeout_ms": 30_000,
        }
    )
