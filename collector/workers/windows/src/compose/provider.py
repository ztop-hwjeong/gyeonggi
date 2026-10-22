import argparse
import json
import sys
from dataclasses import dataclass
from typing import Literal

import psutil
from pydantic import BaseModel, ValidationError

from config import RuntimeSettings, WorkerSettings
from runtime.process import start_supervisor, stop_supervisor
from runtime.state import ProcessStateStore, RuntimeIdentity


@dataclass(frozen=True)
class ProviderOption:
    name: str
    destination: str
    value_type: Literal["string", "integer", "number"]


class ProviderMessage(BaseModel):
    type: Literal["info", "error"]
    message: str


def provider_options() -> tuple[ProviderOption, ...]:
    return (
        ProviderOption("collector-directory", "collector_directory", "string"),
        ProviderOption("runtime-directory", "runtime_directory", "string"),
        ProviderOption("prefect-api-url", "prefect_api_url", "string"),
        ProviderOption("worker-pool", "worker_pool", "string"),
        ProviderOption("worker-limit", "worker_limit", "integer"),
        ProviderOption("worker-restart-delay", "worker_restart_delay", "number"),
        ProviderOption("process-stop-timeout", "process_stop_timeout", "number"),
        ProviderOption("browser-cdp-url", "browser_cdp_url", "string"),
        ProviderOption("browser-profile-directory", "browser_profile_directory", "string"),
        ProviderOption(
            "edge-default-profile-directory", "edge_default_profile_directory", "string"
        ),
        ProviderOption("browser-restart-delay", "browser_restart_delay", "number"),
        ProviderOption("browser-launch-timeout-ms", "browser_launch_timeout_ms", "integer"),
        ProviderOption("browser-connect-timeout-ms", "browser_connect_timeout_ms", "integer"),
        ProviderOption("browser-navigation-timeout-ms", "browser_navigation_timeout_ms", "integer"),
        ProviderOption("browser-operation-attempts", "browser_operation_attempts", "integer"),
        ProviderOption("browser-operation-retry-delay", "browser_operation_retry_delay", "number"),
    )


def emit_metadata(options: tuple[ProviderOption, ...]) -> None:
    parameters = [
        {"name": option.name, "type": option.value_type, "required": False} for option in options
    ]
    print(
        json.dumps(
            {
                "description": "Windows Prefect process worker",
                "up": {"parameters": parameters},
                "down": {"parameters": parameters},
                "stop": {"parameters": parameters},
            }
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("interface", choices=["compose"])
    parser.add_argument("--project-name")
    parser.add_argument("action", choices=["up", "down", "stop", "metadata"])
    parser.add_argument("service", nargs="?")
    options = provider_options()
    for option in options:
        parser.add_argument(f"--{option.name}", dest=option.destination)
    args = parser.parse_intermixed_args(argv)
    if args.action == "metadata":
        emit_metadata(options)
        return 0
    try:
        if sys.platform != "win32":
            raise RuntimeError("Windows host required for the Windows worker provider")
        identity = RuntimeIdentity.model_validate(
            {
                "project": args.project_name,
                "service": args.service,
            }
        )
        values = {
            option.destination: getattr(args, option.destination)
            for option in options
            if getattr(args, option.destination) is not None
        }
        if args.action == "up":
            settings = RuntimeSettings.load(values)
            store = ProcessStateStore(settings.worker.runtime_directory / f"{identity.name}.json")
            start_supervisor(settings, identity, store)
            message = "Windows worker supervisor started"
        else:
            worker = WorkerSettings.model_validate(values)
            store = ProcessStateStore(worker.runtime_directory / f"{identity.name}.json")
            stop_supervisor(store, worker.process_stop_timeout)
            message = "Windows worker stopped"
        print(ProviderMessage(type="info", message=message).model_dump_json())
        return 0
    except (ValidationError, OSError, RuntimeError, psutil.Error) as error:
        print(ProviderMessage(type="error", message=str(error)).model_dump_json())
        return 1


if __name__ == "__main__":
    sys.exit(main())
