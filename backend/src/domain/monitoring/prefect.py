from urllib.parse import quote
from uuid import UUID

import httpx2
from pydantic import ValidationError

from domain.monitoring.config import MonitoringSettings
from domain.monitoring.errors import MonitoringUnavailableError, RunNotFoundError
from domain.monitoring.models import PoolInfo, RunInfo, RunQuery, WorkerInfo


class PrefectMonitor:
    def __init__(self, client: httpx2.AsyncClient, settings: MonitoringSettings) -> None:
        self._client = client
        self._settings = settings

    async def _request(self, method: str, path: str, body: dict | None = None):
        try:
            response = await self._client.request(method, path, json=body)
            response.raise_for_status()
            return response.json()
        except httpx2.HTTPStatusError as error:
            if (
                error.response.status_code == 404
                and method == "GET"
                and path.startswith("flow_runs/")
            ):
                raise RunNotFoundError from error
            raise MonitoringUnavailableError("Prefect 조회 실패") from error
        except (httpx2.RequestError, ValueError) as error:
            raise MonitoringUnavailableError("Prefect 연결 또는 응답 오류") from error

    async def runs(self, query: RunQuery) -> tuple[list[RunInfo], int]:
        criteria = {
            "flows": {"name": {"any_": list(self._settings.monitoring_flow_names)}},
            "flow_runs": {
                "expected_start_time": {
                    "after_": query.since.isoformat(),
                    "before_": query.until.isoformat(),
                }
            },
        }
        if query.state is not None:
            criteria["flow_runs"]["state"] = {"type": {"any_": [query.state]}}
        rows = await self._request(
            "POST",
            "flow_runs/filter",
            {
                **criteria,
                "sort": "EXPECTED_START_TIME_DESC",
                "limit": query.limit,
                "offset": query.offset,
            },
        )
        count = await self._request("POST", "flow_runs/count", criteria)
        try:
            names = {}
            if rows:
                flows = await self._request(
                    "POST",
                    "flows/filter",
                    {
                        "flows": {"id": {"any_": list({row["flow_id"] for row in rows})}},
                        "limit": 200,
                    },
                )
                names = {flow["id"]: flow["name"] for flow in flows}
            return [
                RunInfo.model_validate({**row, "flow_name": names[row["flow_id"]]}) for row in rows
            ], int(count)
        except (ValidationError, TypeError, ValueError, KeyError) as error:
            raise MonitoringUnavailableError("Prefect 실행 응답 형식 오류") from error

    async def run(self, run_id: UUID) -> RunInfo:
        row = await self._request("GET", f"flow_runs/{run_id}")
        # 실행 매개변수·자격 증명·인프라 설정을 API 응답에서 제외하는 허용 목록
        try:
            flow = await self._request("GET", f"flows/{row['flow_id']}")
            if flow["name"] not in self._settings.monitoring_flow_names:
                raise RunNotFoundError
            return RunInfo.model_validate({**row, "flow_name": flow["name"]})
        except (ValidationError, KeyError, TypeError) as error:
            raise MonitoringUnavailableError("Prefect 실행 응답 형식 오류") from error

    async def pools(self) -> list[PoolInfo]:
        rows = await self._request(
            "POST",
            "work_pools/filter",
            {
                "work_pools": {"name": {"any_": list(self._settings.monitoring_pool_names)}},
                "limit": 200,
            },
        )
        pools = []
        try:
            for row in rows:
                workers = []
                offset = 0
                while True:
                    batch = await self._request(
                        "POST",
                        f"work_pools/{quote(row['name'], safe='')}/workers/filter",
                        {"limit": 200, "offset": offset},
                    )
                    workers.extend(WorkerInfo.model_validate(worker) for worker in batch)
                    if len(batch) < 200:
                        break
                    offset += 200
                pools.append(PoolInfo.model_validate({**row, "workers": workers}))
        except (ValidationError, KeyError, TypeError) as error:
            raise MonitoringUnavailableError("Prefect worker 응답 형식 오류") from error
        return pools
