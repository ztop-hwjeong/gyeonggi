import asyncio
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, Mock
from uuid import UUID

import pytest

from analysis.dispatch import dispatch_one
from analysis.models import AnalysisDispatchSettings
from analysis.repository import AnalysisRepository
from flows import analysis_dispatch


def repository_with_row(row):
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.begin.return_value.__aenter__ = AsyncMock(return_value=session)
    session.begin.return_value.__aexit__ = AsyncMock(return_value=None)
    session.execute = AsyncMock(
        side_effect=[Mock(mappings=Mock(return_value=Mock(first=Mock(return_value=row)))), Mock()]
    )
    return cast(AnalysisRepository, Mock(sessions=Mock(return_value=session)))


def test_dispatches_queued_article_with_hashed_idempotency_key() -> None:
    item = {
        "article_id": UUID("11111111-1111-1111-1111-111111111111"),
        "source": "bigkinds",
        "source_id": "https://example.test/a/b",
        "content_hash": "a" * 64,
    }
    repository = repository_with_row(item)
    client = Mock()
    client.read_deployment_by_name.return_value = SimpleNamespace(id="deployment")
    client.create_flow_run_from_deployment.return_value = SimpleNamespace(id="flow-run")
    assert asyncio.run(dispatch_one(repository, client, "analysis/deployment")) is True
    call = client.create_flow_run_from_deployment.call_args
    assert call.kwargs["parameters"]["source_id"] == item["source_id"]
    assert call.kwargs["idempotency_key"].startswith("analysis:")
    assert len(call.kwargs["idempotency_key"]) == len("analysis:") + 64


def test_dispatch_returns_false_without_queued_article() -> None:
    repository = repository_with_row(None)
    assert asyncio.run(dispatch_one(repository, Mock(), "analysis/deployment")) is False


def test_dispatch_flow_submits_all_queued_articles(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.__enter__.return_value = Mock()
    submit = AsyncMock(side_effect=[True, True, False])

    class Scope:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, kind):
            return {
                AnalysisRepository: Mock(),
                AnalysisDispatchSettings: AnalysisDispatchSettings(),
            }[kind]

    class Container:
        def __call__(self):
            return Scope()

        async def close(self):
            return None

    monkeypatch.setattr(analysis_dispatch, "create_analysis_container", Container)
    monkeypatch.setattr(analysis_dispatch, "get_client", lambda **kwargs: client)
    monkeypatch.setattr(analysis_dispatch, "dispatch_one", submit)
    monkeypatch.setattr(analysis_dispatch, "get_run_logger", Mock(return_value=Mock()))

    assert asyncio.run(analysis_dispatch.dispatch_article_analysis.fn()) == {"submitted": 2}
    assert submit.await_count == 3
