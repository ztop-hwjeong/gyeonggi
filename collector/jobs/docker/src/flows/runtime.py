import platform

from prefect import flow, get_run_logger


def require_platform(expected: str) -> None:
    actual = platform.system()
    if actual != expected:
        raise RuntimeError(f"실행 환경 불일치: {expected} 필요, 현재 {actual}")


def runtime_info() -> dict[str, str]:
    return {
        "hostname": platform.node(),
        "platform": platform.system(),
        "python": platform.python_version(),
    }


@flow(name="docker-runtime-check")
def docker_runtime_check() -> dict[str, str]:
    require_platform("Linux")
    result = runtime_info()
    get_run_logger().info("Docker 실행 환경 확인: %s", result)
    return result
