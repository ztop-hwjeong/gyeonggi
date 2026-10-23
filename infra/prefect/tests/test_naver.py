import asyncio
import json
from unittest.mock import AsyncMock, Mock

import pytest
from prefect.exceptions import ObjectNotFound
from pydantic import ValidationError

import register_naver


def settings():
    return register_naver.NaverInitializationSettings.model_validate(
        {
            "X-NCP-APIGW-API-KEY-ID": "test-id",
            "X-NCP-APIGW-API-KEY": "test-secret",
            "naver_credentials_block": "test-naver",
            "naver_rate_limit_name": "test-limit",
        }
    )


def test_environment_credentials_are_saved_as_secret_without_exposing_values(monkeypatch):
    block = Mock(asave=AsyncMock())
    secret = Mock(return_value=block)
    client = AsyncMock()
    context = AsyncMock()
    context.__aenter__.return_value = client
    monkeypatch.setattr(register_naver, "Secret", secret)
    monkeypatch.setattr(register_naver, "get_client", lambda: context)
    asyncio.run(register_naver.initialize(settings()))
    value = secret.call_args.kwargs["value"]
    assert "test-secret" not in repr(value)
    assert json.loads(value.get_secret_value()) == {
        "client_id": "test-id",
        "client_secret": "test-secret",
    }
    block.asave.assert_awaited_once_with("test-naver", overwrite=True)
    client.create_global_concurrency_limit.assert_not_awaited()


def test_missing_limit_is_created_once(monkeypatch):
    client = AsyncMock()
    client.read_global_concurrency_limit_by_name.side_effect = ObjectNotFound(http_exc=Mock())
    context = AsyncMock()
    context.__aenter__.return_value = client
    monkeypatch.setattr(register_naver, "get_client", lambda: context)
    monkeypatch.setattr(register_naver, "Secret", Mock(return_value=Mock(asave=AsyncMock())))
    asyncio.run(register_naver.initialize(settings()))
    assert client.create_global_concurrency_limit.await_count == 1


def test_missing_secret_fails_with_redacted_input():
    with pytest.raises(ValidationError) as error:
        register_naver.NaverInitializationSettings.model_validate(
            {
                "X-NCP-APIGW-API-KEY-ID": "private-value",
            }
        )
    assert "private-value" not in str(error.value)
