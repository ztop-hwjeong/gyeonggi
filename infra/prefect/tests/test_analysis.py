import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from httpx import HTTPStatusError, Request, Response
from prefect.exceptions import ObjectNotFound
from pydantic import SecretStr

import register_analysis


def settings() -> register_analysis.AnalysisInitializationSettings:
    return register_analysis.AnalysisInitializationSettings(openai_api_key=SecretStr("test-key"))


def test_creates_missing_openai_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    async def missing(name: str):
        raise ValueError from ObjectNotFound(
            http_exc=HTTPStatusError(
                "missing", request=Request("GET", "http://test"), response=Response(404)
            )
        )

    block = Mock()
    block.asave = AsyncMock()
    monkeypatch.setattr(register_analysis.Secret, "aload", missing)
    monkeypatch.setattr(register_analysis.Secret, "__new__", lambda cls, **kwargs: block)
    asyncio.run(register_analysis.initialize(settings()))
    block.asave.assert_awaited_once_with("openai-api-key")


def test_rejects_different_existing_openai_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    async def existing(name: str):
        return Mock(get=Mock(return_value="other-key"))

    monkeypatch.setattr(register_analysis.Secret, "aload", existing)
    with pytest.raises(RuntimeError, match="불일치"):
        asyncio.run(register_analysis.initialize(settings()))
