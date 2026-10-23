import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx2
import pytest
from dishka import Provider, Scope, make_async_container, provide
from fastapi.testclient import TestClient
from pydantic import AnyHttpUrl
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from domain.monitoring.config import MonitoringSettings
from domain.monitoring.errors import MonitoringUnavailableError
from domain.monitoring.models import (
    ErrorPage,
    RunQuery,
    SearchMetrics,
    SearchProgress,
    StreamPage,
    Window,
)
from domain.monitoring.prefect import PrefectMonitor
from domain.monitoring.repository import MonitoringRepository
from main import create_app


@pytest.fixture
def monitor_setup():
    repository = AsyncMock(spec=MonitoringRepository)
    calls = []
    run_id, flow_id = uuid4(), uuid4()
    now = datetime.now(UTC).isoformat()

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content) if request.content else None
        calls.append((request.url.path, body))
        path = request.url.path
        if path == "/api/flow_runs/count":
            data = 42
        elif path == "/api/flows/filter":
            data = [{"id": str(flow_id), "name": "collect-article-details"}]
        elif path == "/api/flow_runs/filter" or path == f"/api/flow_runs/{run_id}":
            run = {
                "id": str(run_id),
                "flow_id": str(flow_id),
                "name": "test-run",
                "state": {"type": "COMPLETED", "name": "Completed", "timestamp": now},
                "expected_start_time": now,
                "start_time": now,
                "end_time": now,
                "estimated_run_time": 10,
                "parameters": {"secret": "MUST-NOT-RETURN"},
            }
            data = [run] if path.endswith("filter") else run
        elif path == f"/api/flows/{flow_id}":
            data = {"name": "collect-article-details"}
        elif path == "/api/work_pools/filter":
            data = [
                {
                    "name": "windows-collector",
                    "type": "process",
                    "status": "READY",
                    "is_paused": False,
                    "base_job_template": "private",
                }
            ]
        elif path.endswith("/workers/filter"):
            data = [
                {
                    "id": str(uuid4()),
                    "name": "worker",
                    "status": "OFFLINE",
                    "last_heartbeat_time": now,
                    "heartbeat_interval_seconds": 30,
                }
            ]
        else:
            return httpx2.Response(404, json={"detail": "missing"})
        return httpx2.Response(200, json=data)

    class TestProvider(Provider):
        @provide(scope=Scope.APP)
        async def monitor(self) -> AsyncIterator[PrefectMonitor]:
            async with httpx2.AsyncClient(
                base_url="http://prefect.test/api/",
                transport=httpx2.MockTransport(handler),
            ) as client:
                yield PrefectMonitor(
                    client,
                    MonitoringSettings(
                        prefect_api_url=AnyHttpUrl("http://prefect.test/api"),
                    ),
                )

        @provide(scope=Scope.REQUEST)
        def repo(self) -> MonitoringRepository:
            return repository

    repository.progress.return_value = {}
    container = make_async_container(TestProvider())
    with TestClient(create_app(container)) as client:
        yield client, repository, calls, run_id


def test_runs_filter_pagination_and_private_fields(monitor_setup):
    client, _, calls, _ = monitor_setup
    response = client.get("/monitoring/runs?state=FAILED&limit=2&offset=10")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 42
    assert data["offset"] == 10
    assert "parameters" not in data["items"][0]
    assert "MUST-NOT-RETURN" not in response.text
    request = calls[0][1]
    assert request["flow_runs"]["state"]["type"]["any_"] == ["FAILED"]
    assert request["offset"] == 10
    assert set(request["flows"]["name"]["any_"]) == {
        "bigkinds-collect-list",
        "collect-article-details",
        "naver-collect-list",
        "collect-naver-cafe-details",
        "managed-collection",
    }


@pytest.mark.parametrize(
    "query",
    [
        "limit=201",
        "offset=-1",
        "state=BOGUS",
        "state=SUSPENDED",
        "since=2026-10-23T00:00:00",
        "since=2026-10-24T00:00:00Z&until=2026-10-23T00:00:00Z",
        "since=2026-01-01T00:00:00Z&until=2026-10-23T00:00:00Z",
    ],
)
def test_invalid_monitoring_query_is_rejected_before_upstream(monitor_setup, query):
    client, _, calls, _ = monitor_setup
    assert client.get("/monitoring/runs?" + query).status_code == 422
    assert calls == []


def test_unknown_run_returns_404(monitor_setup):
    client, _, _, _ = monitor_setup
    assert client.get(f"/monitoring/runs/{uuid4()}").status_code == 404


def test_worker_offline_and_heartbeat_are_preserved(monitor_setup):
    client, _, _, _ = monitor_setup
    response = client.get("/monitoring/workers")
    assert response.status_code == 200
    pool = response.json()["pools"][0]
    assert pool["workers"][0]["status"] == "OFFLINE"
    assert pool["workers"][0]["last_heartbeat_time"] is not None
    assert "base_job_template" not in pool


def test_errors_filter_is_forwarded_and_storage_failure_is_503(monitor_setup):
    client, repository, _, _ = monitor_setup
    repository.errors.return_value = ErrorPage(items=[], total=0, limit=50, offset=0)
    response = client.get("/monitoring/errors?stage=browser_fetch&recovered=false")
    assert response.status_code == 200
    query = repository.errors.call_args.args[0]
    assert query.stage == "browser_fetch" and query.recovered is False
    repository.errors.side_effect = MonitoringUnavailableError("수집 저장소 조회 실패")
    assert client.get("/monitoring/errors").status_code == 503


def test_prefect_outage_is_503_without_transport_details():
    async def check():
        def handler(request):
            raise httpx2.ConnectError("internal-private-address", request=request)

        async with httpx2.AsyncClient(
            base_url="http://prefect.test/api/",
            transport=httpx2.MockTransport(handler),
        ) as client:
            monitor = PrefectMonitor(
                client,
                MonitoringSettings(
                    prefect_api_url=AnyHttpUrl("http://prefect.test/api"),
                ),
            )
            with pytest.raises(MonitoringUnavailableError, match="연결") as error:
                await monitor.runs(RunQuery())
            assert "private" not in str(error.value)

    asyncio.run(check())


def test_missing_prefect_list_route_is_unavailable_instead_of_unknown_run():
    async def check():
        async with httpx2.AsyncClient(
            base_url="http://prefect.test/api/",
            transport=httpx2.MockTransport(lambda request: httpx2.Response(404)),
        ) as client:
            monitor = PrefectMonitor(
                client, MonitoringSettings(prefect_api_url=AnyHttpUrl("http://prefect.test/api"))
            )
            with pytest.raises(MonitoringUnavailableError):
                await monitor.runs(RunQuery())

    asyncio.run(check())


@pytest.mark.parametrize("collected,failed,expected", [(3, 1, 0.75), (0, 0, None)])
def test_success_rate_uses_finished_article_results(collected, failed, expected):
    async def check():
        repo = MonitoringRepository(AsyncMock(spec=AsyncSession))
        repo._rows = AsyncMock(
            side_effect=[
                [{"status": "running", "count": 1, "requested": 10}],
                [
                    {"status": "collected", "count": collected},
                    {"status": "failed", "count": failed},
                ],
                [],
                [{"count": 2, "bytes": 100}],
                [],
                [{"finished_at": None}],
            ]
        )
        result = await repo.metrics(Window())
        assert result.success_rate == expected
        assert result.processed_articles == collected + failed
        assert result.requested_articles == 10

    asyncio.run(check())


def test_database_failure_does_not_look_like_empty_metrics():
    async def check():
        session = AsyncMock(spec=AsyncSession)
        session.execute.side_effect = OperationalError("private SQL", {}, Exception("private"))
        with pytest.raises(MonitoringUnavailableError, match="저장소"):
            await MonitoringRepository(session).metrics(Window())

    asyncio.run(check())


def test_search_partial_progress_is_distinct_from_prefect_completion(monitor_setup):
    client, repository, _, run_id = monitor_setup
    now = datetime.now(UTC)
    repository.progress.return_value = {
        run_id: SearchProgress(
            channel="news",
            query="교육",
            status="partial",
            started_at=now,
            finished_at=now,
            pages_collected=3,
            retrieved_count=60,
            new_count=2,
            updated_count=0,
            total_count=1000,
            cursor_advanced=False,
            stop_reason="페이지 상한",
            error_type=None,
            error_code=None,
        )
    }
    data = client.get("/monitoring/runs").json()["items"][0]
    assert data["state"]["type"] == "COMPLETED"
    assert data["collection"]["status"] == "partial"
    assert not data["collection"]["cursor_advanced"]


def test_search_streams_keep_old_cursors_visible_and_support_channel_filter(monitor_setup):
    client, repository, _, _ = monitor_setup
    repository.streams.return_value = StreamPage(items=[], total=4, limit=1, offset=10)
    response = client.get("/monitoring/search-streams?channel=cafearticle&limit=1&offset=10")
    assert response.status_code == 200 and response.json()["total"] == 4
    query = repository.streams.call_args.args[0]
    assert query.channel == "cafearticle" and query.offset == 10
    assert not hasattr(query, "since")


def test_search_metrics_expose_shared_request_usage(monitor_setup):
    client, repository, _, _ = monitor_setup
    now = datetime.now(UTC)
    repository.search_metrics.return_value = SearchMetrics(
        since=now,
        until=now,
        run_status_counts={},
        pages_collected=0,
        retrieved_count=0,
        new_count=0,
        updated_count=0,
        raw_response_count=0,
        raw_response_bytes=0,
        requests_today=25,
    )
    response = client.get("/monitoring/search-metrics?channel=blog")
    assert response.status_code == 200 and response.json()["requests_today"] == 25
    assert repository.search_metrics.call_args.args[0].channel == "blog"
