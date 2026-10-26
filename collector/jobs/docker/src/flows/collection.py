from datetime import timedelta
from math import ceil
from typing import Literal, cast
from uuid import UUID

from collector_http.client import ChromiumHttpClient
from collector_http.config import HttpSettings
from collector_storage.objects import RawObjectStore

from control.models import ControlSettings, ManagedRequest
from control.repository import ControlRepository
from flows.bigkinds import acquire_request as acquire_bigkinds
from flows.naver import acquire_request as acquire_naver
from flows.naver import collect as collect_naver
from sources.bigkinds.client import BigKindsClient
from sources.bigkinds.config import BigKindsSettings
from sources.bigkinds.models import ListCollectionRequest
from sources.bigkinds.normalization import normalize_listing, parse_search_response
from sources.naver.client import NaverApiError, NaverClient, parse_response
from sources.naver.config import NaverCredentials, NaverSettings
from sources.naver.models import SearchRequest
from sources.naver.normalization import normalize_item
from sources.naver.storage import SearchRepository


def collect_bigkinds(
    request: ManagedRequest,
    repository: ControlRepository,
    objects: RawObjectStore,
    settings: ControlSettings,
) -> tuple[str, dict]:
    source, http = BigKindsSettings.model_validate({}), HttpSettings()

    def acquire() -> None:
        repository.check_cancelled(request.id)
        acquire_bigkinds(source, http)

    summary: dict = {"pages_collected": 0, "retrieved_count": 0, "total_count": 0, "days": []}
    complete = True
    current = request.start_date
    with ChromiumHttpClient(http, acquire) as transport:
        client = BigKindsClient(source, transport)
        client.warmup()
        while current <= request.end_date:
            end = request.end_date if request.mode == "preview" else current
            query = ListCollectionRequest(
                search_key=" OR ".join(f'"{term}"' for term in request.definition.terms),
                start_date=current,
                end_date=end,
            )
            page_number, expected, seen = 1, None, set()
            day_complete = True
            while True:
                body = client.search(query, page_number)
                repository.save_response(request, objects, summary["pages_collected"] + 1, body)
                page = parse_search_response(body)
                items = [
                    normalize_listing(item).model_dump(mode="json") for item in page.result_list
                ]
                ids = {item["source_id"] for item in items}
                if expected is None:
                    expected = page.total_count
                    summary["total_count"] += expected
                if page.total_count != expected:
                    day_complete = False
                repository.save_items(request, items)
                summary["pages_collected"] += 1
                summary["retrieved_count"] += len(ids - seen)
                repeated = bool(ids) and ids <= seen
                seen.update(ids)
                repository.progress(request.id, summary)
                if request.mode == "preview":
                    return "completed", summary
                if repeated or (not items and expected):
                    day_complete = False
                    break
                if page_number >= max(1, ceil(page.total_count / query.page_size)):
                    break
                if page_number >= settings.bigkinds_max_pages_per_day:
                    day_complete = False
                    break
                page_number += 1
            day_complete = day_complete and len(seen) == expected
            summary["days"].append(
                {
                    "date": current.isoformat(),
                    "total_count": expected,
                    "retrieved_count": len(seen),
                    "complete": day_complete,
                }
            )
            repository.progress(request.id, summary)
            complete = complete and day_complete
            current += timedelta(days=1)
    return ("completed" if complete else "partial"), summary


def collect_naver_request(
    request: ManagedRequest,
    flow_run_id: UUID,
    repository: ControlRepository,
    objects: RawObjectStore,
    settings: NaverSettings,
    credentials: NaverCredentials,
) -> tuple[str, dict]:
    if request.mode == "backfill":
        raise ValueError("네이버 기간 수집 미지원")
    search = SearchRequest(
        channel=cast(Literal["news", "blog"], request.source.removeprefix("naver_")),
        terms=request.definition.terms,
    )
    searches = SearchRepository(repository.settings, repository.password)
    http = HttpSettings()
    if request.mode != "preview":
        try:
            summary = collect_naver(
                search, flow_run_id, searches, objects, settings, credentials, http
            )
            return summary.status, summary.model_dump(mode="json")
        finally:
            repository.save_items(request, repository.naver_items(flow_run_id))

    def acquire() -> None:
        repository.check_cancelled(request.id)
        acquire_naver(settings, http, searches)

    with ChromiumHttpClient(http, acquire) as transport:
        response = NaverClient(transport, settings, credentials).fetch(search, 1)
        repository.save_response(request, objects, 1, response.content)
        try:
            page = parse_response(response, 1)
        except NaverApiError as error:
            if error.status == 429 or error.retry_after_seconds is not None:
                searches.pause_requests(error.retry_after_seconds or settings.error_pause_seconds)
            raise
        items = [
            normalize_item(search.channel, item).model_dump(mode="json") for item in page.items
        ]
        repository.save_items(request, items)
        return "completed", {
            "pages_collected": 1,
            "total_count": page.total,
            "retrieved_count": len(items),
        }
