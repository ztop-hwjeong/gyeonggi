import asyncio
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from prefect.client.schemas.objects import State, StateType

from analysis.cache import PostgresResponseCache
from flows import report_relevance as relevance
from relevance.client import RelevanceAnalyzer
from relevance.dispatch import dispatch_one, recover_expired
from relevance.models import RelevanceInput
from relevance.repository import RelevanceRepository


def test_prefect_entrypoints_load_without_package_name_collision():
    project = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from prefect.flows import load_flow_from_entrypoint as load; "
            "load('src/flows/relevance_dispatch.py:dispatch_report_relevance'); "
            "load('src/flows/report_relevance.py:analyze_report_relevance'); "
            "load('src/flows/article_analysis.py:analyze_stored_article')",
        ],
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(project / "src")},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def item() -> RelevanceInput:
    return RelevanceInput(
        run_id=uuid4(), title="경기교육 정책", body="본문 근거 문장", criteria="교육 정책"
    )


def test_invalid_evidence_never_opens_completion_transaction() -> None:
    repository = RelevanceRepository(Mock())
    with pytest.raises(ValueError, match="근거 필요"):
        asyncio.run(
            repository.complete(
                item(), {"relevance": "related", "reason": "판정", "evidence": []}, {}
            )
        )
    with pytest.raises(ValueError, match="원문 불일치"):
        asyncio.run(
            repository.complete(
                item(), {"relevance": "unrelated", "reason": "판정", "evidence": ["없는 인용"]}, {}
            )
        )


def test_relevance_flow_does_not_call_model_when_claim_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = Mock(claim=AsyncMock(return_value=None), fail=AsyncMock())
    analyzer = Mock(analyze=AsyncMock())
    cache = Mock(acommit=AsyncMock())
    closed = []

    class Scope:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, kind):
            return {
                RelevanceRepository: repository,
                RelevanceAnalyzer: analyzer,
                PostgresResponseCache: cache,
            }[kind]

    class Container:
        def __call__(self):
            return Scope()

        async def close(self):
            closed.append(True)

    monkeypatch.setattr(relevance, "create_analysis_container", Container)
    asyncio.run(relevance.analyze_report_relevance.fn(uuid4()))
    analyzer.analyze.assert_not_awaited()
    assert closed == [True]


def test_dispatch_submission_failure_marks_row_and_allows_next_attempt() -> None:
    session = Mock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.begin.return_value.__aenter__ = AsyncMock(return_value=session)
    session.begin.return_value.__aexit__ = AsyncMock(return_value=None)
    row = {"id": uuid4(), "submission_attempts": 0}
    session.execute = AsyncMock(
        side_effect=[
            Mock(mappings=Mock(return_value=Mock(one_or_none=Mock(return_value=row)))),
            Mock(),
        ]
    )
    repository = Mock(sessions=Mock(return_value=session))
    client = Mock()
    client.read_deployment_by_name.return_value = Mock(id="deployment")
    client.create_flow_run_from_deployment.side_effect = RuntimeError("unavailable")

    assert asyncio.run(dispatch_one(repository, client, "relevance/deployment")) is True
    assert session.execute.await_count == 2
    values = session.execute.await_args_list[-1].args[0]._values
    assert values["status"].value == "failed"
    assert values["error"].value == "submission_RuntimeError"


@pytest.mark.parametrize("state_type", [StateType.SCHEDULED, StateType.FAILED, None])
def test_expired_submitted_checks_prefect_before_failure(state_type) -> None:
    session = Mock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.begin.return_value.__aenter__ = AsyncMock(return_value=session)
    session.begin.return_value.__aexit__ = AsyncMock(return_value=None)
    row = {"id": uuid4(), "status": "submitted", "flow_run_id": uuid4()}
    session.execute = AsyncMock(
        side_effect=[Mock(mappings=Mock(return_value=Mock(all=Mock(return_value=[row])))), Mock()]
    )
    repository = Mock(sessions=Mock(return_value=session))
    client = Mock()
    if state_type is None:
        client.read_flow_run.side_effect = RuntimeError("temporarily unavailable")
    else:
        client.read_flow_run.return_value = Mock(state=State(type=state_type))
    asyncio.run(recover_expired(repository, client))
    if state_type is None:
        assert session.execute.await_count == 1
        return
    values = session.execute.await_args_list[-1].args[0]._values
    if state_type == StateType.SCHEDULED:
        assert "lease_expires_at" in values and "status" not in values
    else:
        assert values["status"].value == "failed"
        assert values["error"].value == "flow_failed"
