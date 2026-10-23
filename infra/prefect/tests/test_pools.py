import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import HTTPStatusError, Request, Response
from prefect.exceptions import ObjectNotFound

import register_pools


def client_context(monkeypatch: pytest.MonkeyPatch, client: AsyncMock) -> None:
    context = AsyncMock()
    context.__aenter__.return_value = client
    monkeypatch.setattr(register_pools, "get_client", lambda: context)


def test_creates_separate_docker_and_process_pools(monkeypatch: pytest.MonkeyPatch) -> None:
    client = AsyncMock()
    client.read_work_pool.side_effect = ObjectNotFound(
        http_exc=HTTPStatusError(
            "Not found", request=Request("GET", "http://test"), response=Response(404)
        )
    )
    client_context(monkeypatch, client)
    asyncio.run(register_pools.register_pools())
    created = [call.args[0] for call in client.create_work_pool.await_args_list]
    assert [(pool.name, pool.type) for pool in created] == [
        ("docker-collector", "docker"),
        ("windows-collector", "process"),
    ]


def test_preserves_existing_pool_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    client = AsyncMock()
    client.read_work_pool.side_effect = [
        SimpleNamespace(type="docker"),
        SimpleNamespace(type="process"),
    ]
    client_context(monkeypatch, client)
    asyncio.run(register_pools.register_pools())
    client.create_work_pool.assert_not_awaited()


def test_rejects_existing_pool_with_wrong_type(monkeypatch: pytest.MonkeyPatch) -> None:
    client = AsyncMock()
    client.read_work_pool.return_value = SimpleNamespace(type="process")
    client_context(monkeypatch, client)
    with pytest.raises(RuntimeError, match="pool의 타입 불일치"):
        asyncio.run(register_pools.register_pools())
    client.create_work_pool.assert_not_awaited()


def test_creates_missing_shared_request_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    client = AsyncMock()
    client.read_work_pool.side_effect = [
        SimpleNamespace(type="docker"),
        SimpleNamespace(type="process"),
    ]
    client.read_global_concurrency_limit_by_name.side_effect = ObjectNotFound(
        http_exc=HTTPStatusError(
            "Not found", request=Request("GET", "http://test"), response=Response(404)
        )
    )
    client_context(monkeypatch, client)
    asyncio.run(register_pools.register_pools())
    created = client.create_global_concurrency_limit.await_args.args[0]
    assert created.limit == 1
    assert created.slot_decay_per_second > 0


def test_preserves_existing_request_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    client = AsyncMock()
    client.read_work_pool.side_effect = [
        SimpleNamespace(type="docker"),
        SimpleNamespace(type="process"),
    ]
    client_context(monkeypatch, client)
    asyncio.run(register_pools.register_pools())
    client.create_global_concurrency_limit.assert_not_awaited()
