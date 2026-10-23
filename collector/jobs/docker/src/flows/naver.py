from datetime import UTC, datetime
from functools import partial
from typing import cast
from uuid import UUID

import psycopg
from collector_http.client import ChromiumHttpClient
from collector_http.config import HttpSettings
from collector_storage.config import DatabaseSettings, ObjectStorageSettings
from collector_storage.objects import ObjectCredentials, RawObjectStore
from prefect import flow, get_run_logger, task
from prefect.blocks.system import Secret
from prefect.cache_policies import NO_CACHE
from prefect.client.orchestration import get_client
from prefect.concurrency.sync import rate_limit
from prefect.context import FlowRunContext
from pydantic import SecretStr

from sources.naver.client import NaverApiError, NaverClient, parse_response
from sources.naver.config import NaverCredentials, NaverSettings
from sources.naver.models import Listing, Pagination, SearchPage, SearchRequest, SearchSummary
from sources.naver.normalization import normalize_item
from sources.naver.storage import SearchRepository


def acquire_request(
    settings: NaverSettings, http: HttpSettings, repository: SearchRepository
) -> None:
    with get_client(sync_client=True) as client:
        limit = client.read_global_concurrency_limit_by_name(settings.rate_limit_name)
    if not limit.active or limit.limit != 1 or limit.slot_decay_per_second <= 0:
        raise RuntimeError("네이버 요청 제한 비활성 또는 설정 오류")
    rate_limit(
        settings.rate_limit_name, timeout_seconds=http.rate_limit_timeout_seconds, strict=True
    )
    repository.reserve_request(settings.daily_request_limit)


@task(name="naver-fetch-list-page", cache_policy=NO_CACHE, persist_result=False, retries=0)
def fetch_page(
    client: NaverClient,
    request: SearchRequest,
    start: int,
    repository: SearchRepository,
    connection: psycopg.Connection,
    objects: RawObjectStore,
    summary: SearchSummary,
) -> tuple[SearchPage, UUID]:
    response = client.fetch(request, start)
    response_id = repository.save_response(
        connection,
        objects,
        summary,
        start,
        response.status_code,
        response.headers.get("Content-Type", ""),
        response.content,
    )
    return parse_response(response, start), response_id


@task(name="naver-normalize-list-page", cache_policy=NO_CACHE, persist_result=False, retries=0)
def store_page(
    repository: SearchRepository,
    connection: psycopg.Connection,
    summary: SearchSummary,
    response_id: UUID,
    page: SearchPage,
) -> tuple[list[Listing], int, int]:
    items = [normalize_item(summary.channel, item) for item in page.items]
    new, updated = repository.save_items(connection, summary, response_id, items)
    return items, new, updated


def collect(
    request: SearchRequest,
    run_id: UUID,
    repository: SearchRepository,
    objects: RawObjectStore,
    settings: NaverSettings,
    credentials: NaverCredentials,
    http_settings: HttpSettings,
) -> SearchSummary:
    summary = SearchSummary(
        run_id=run_id,
        stream_key=request.stream_key,
        channel=request.channel,
        query=request.query,
        started_at=datetime.now(UTC),
    )
    with repository.lock(request) as connection:
        pagination = Pagination(
            request,
            repository.cursor(connection, request.stream_key),
            settings.overlap_pages,
            settings.date_overlap_days,
        )
        repository.save_run(connection, summary)
        try:
            with ChromiumHttpClient(
                http_settings, partial(acquire_request, settings, http_settings, repository)
            ) as http:
                client = NaverClient(http, settings, credentials)
                complete = False
                for index in range(request.max_pages):
                    start = 1 + index * request.page_size
                    if start > 1000:
                        summary.stop_reason = "API 시작 위치 상한"
                        break
                    page, response_id = fetch_page(
                        client, request, start, repository, connection, objects, summary
                    )
                    items, new, updated = store_page(
                        repository, connection, summary, response_id, page
                    )
                    summary.pages_collected += 1
                    summary.retrieved_count += len(items)
                    summary.new_count += new
                    summary.updated_count += updated
                    summary.total_count = page.total
                    complete, reason = pagination.accept(page, items)
                    summary.missing_date_count = pagination.missing_date_count
                    summary.date_boundary_reached = pagination.date_boundary_reached
                    repository.save_run(connection, summary)
                    if complete or reason is not None:
                        summary.stop_reason = reason
                        break
                summary.status = "completed" if complete else "partial"
                summary.cursor_advanced = complete
                if summary.stop_reason is None:
                    summary.stop_reason = "페이지 상한 내 수집 경계·겹침 구간 미확인"
        except Exception as error:
            summary.status = "failed"
            summary.error_type = type(error).__name__
            summary.stop_reason = "수집 오류로 커서 유지"
            if isinstance(error, NaverApiError):
                summary.error_code = error.code
                if error.status == 429 or error.retry_after_seconds is not None:
                    repository.pause_requests(
                        error.retry_after_seconds or settings.error_pause_seconds
                    )
            summary.finished_at = datetime.now(UTC)
            repository.finish(
                connection, summary, pagination.next_cursor(run_id, summary.finished_at)
            )
            raise
        summary.finished_at = datetime.now(UTC)
        repository.finish(connection, summary, pagination.next_cursor(run_id, summary.finished_at))
    return summary


@flow(name="naver-collect-list", persist_result=False, log_prints=False)
def naver_collect_list(request: SearchRequest) -> SearchSummary:
    context = FlowRunContext.get()
    if context is None or context.flow_run is None:
        raise RuntimeError("Prefect flow 실행 문맥 필요")
    settings = NaverSettings.model_validate({})
    database = DatabaseSettings.model_validate({})
    storage = ObjectStorageSettings.model_validate({})
    password = cast(Secret, Secret.load(database.database_password_block)).get()
    credentials = cast(Secret, Secret.load(settings.credentials_block)).get()
    object_credentials = cast(Secret, Secret.load(storage.credentials_block)).get()
    repository = SearchRepository(database, SecretStr(cast(str, password)))
    with RawObjectStore(storage, ObjectCredentials.model_validate(object_credentials)) as objects:
        summary = collect(
            request,
            context.flow_run.id,
            repository,
            objects,
            settings,
            NaverCredentials.model_validate(credentials),
            HttpSettings(),
        )
    get_run_logger().info(
        "네이버 %s: %s, 조회 %s건, 신규 %s건, 커서 갱신 %s",
        summary.channel,
        summary.status,
        summary.retrieved_count,
        summary.new_count,
        summary.cursor_advanced,
    )
    return summary
