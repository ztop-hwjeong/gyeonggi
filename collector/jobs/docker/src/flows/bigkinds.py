from datetime import UTC, datetime
from functools import partial
from math import ceil
from pathlib import Path
from uuid import UUID

from collector_http.client import ChromiumHttpClient, TransientHttpError
from collector_http.config import HttpSettings
from prefect import Task, flow, get_run_logger, task
from prefect.cache_policies import NO_CACHE
from prefect.client.orchestration import get_client
from prefect.client.schemas.objects import State, TaskRun
from prefect.concurrency.sync import rate_limit
from prefect.context import FlowRunContext

from sources.bigkinds.client import BigKindsClient
from sources.bigkinds.config import BigKindsSettings, CollectionSettings
from sources.bigkinds.models import (
    CollectionSummary,
    ListCollectionRequest,
    NormalizedPage,
    StoredResponse,
)
from sources.bigkinds.normalization import normalize_listing, parse_search_response
from sources.bigkinds.storage import (
    UnexpectedPaginationError,
    finalize_collection,
    store_listings,
    store_response,
    write_model,
)


def retry_transient(task: Task, task_run: TaskRun, state: State) -> bool:
    return isinstance(state.result(raise_on_failure=False), TransientHttpError)


def acquire_request(settings: BigKindsSettings, http_settings: HttpSettings) -> None:
    with get_client(sync_client=True) as client:
        limit = client.read_global_concurrency_limit_by_name(settings.rate_limit_name)
    if not limit.active or limit.limit != 1 or limit.slot_decay_per_second <= 0:
        raise RuntimeError("활성 상태의 단일 슬롯 요청 속도 제한 필요")
    rate_limit(
        settings.rate_limit_name,
        occupy=1,
        timeout_seconds=http_settings.rate_limit_timeout_seconds,
        strict=True,
    )


@task(name="initialize-list-collection", cache_policy=NO_CACHE, persist_result=False)
def initialize_collection(
    run_id: UUID, request: ListCollectionRequest, directory: Path, impersonate: str
) -> CollectionSummary:
    output = directory / "bigkinds" / str(run_id)
    output.mkdir(parents=True, exist_ok=True)
    summary = CollectionSummary(
        run_id=str(run_id),
        status="running",
        started_at=datetime.now(UTC),
        request=request,
        impersonate=impersonate,
        output_directory=output,
    )
    write_model(output / "manifest.json", summary)
    return summary


@task(name="bigkinds-open-session", cache_policy=NO_CACHE, persist_result=False)
def open_session(client: BigKindsClient, summary: CollectionSummary) -> CollectionSummary:
    client.warmup()
    return summary


@task(name="bigkinds-fetch-list-page", cache_policy=NO_CACHE, persist_result=False)
def fetch_page(
    client: BigKindsClient,
    request: ListCollectionRequest,
    summary: CollectionSummary,
    page_number: int,
) -> StoredResponse:
    body = client.search(request, page_number)
    return store_response(summary.output_directory, request, page_number, body)


@task(name="bigkinds-normalize-list-page", cache_policy=NO_CACHE, persist_result=False)
def normalize_page(
    response: StoredResponse,
    summary: CollectionSummary,
    previous_ids: frozenset[str] = frozenset(),
) -> NormalizedPage:
    page = parse_search_response(response.body_path.read_bytes())
    articles = [normalize_listing(item) for item in page.result_list]
    if not articles and page.total_count > 0:
        raise UnexpectedPaginationError("검색 건수가 있으나 페이지 결과가 비어 있음")
    if articles and all(article.source_id in previous_ids for article in articles):
        raise UnexpectedPaginationError("페이지 이동 후 새로운 기사 없음")
    result = store_listings(
        summary.output_directory, response.page_number, page.total_count, articles
    )
    get_run_logger().info(
        "목록 %s페이지: %s건, 소스 검색 건수 %s건",
        response.page_number,
        len(articles),
        page.total_count,
    )
    return result


@task(name="finalize-list-collection", cache_policy=NO_CACHE, persist_result=False)
def finish_collection(summary: CollectionSummary, pages: list[NormalizedPage]) -> CollectionSummary:
    return finalize_collection(summary, pages)


@flow(name="bigkinds-collect-list", persist_result=False)
def bigkinds_collect_list(request: ListCollectionRequest) -> CollectionSummary:
    http_settings = HttpSettings()
    source_settings = BigKindsSettings.model_validate({})
    output_settings = CollectionSettings.model_validate({})
    context = FlowRunContext.get()
    if context is None or context.flow_run is None:
        raise RuntimeError("Prefect flow 실행 문맥 필요")
    run_id = context.flow_run.id
    summary = initialize_collection(
        run_id, request, output_settings.output_directory, http_settings.impersonate
    )
    pages: list[NormalizedPage] = []
    fetch = fetch_page.with_options(
        retries=http_settings.retries,
        retry_delay_seconds=http_settings.retry_delay_seconds,
        retry_condition_fn=retry_transient,
    )
    try:
        with ChromiumHttpClient(
            http_settings, partial(acquire_request, source_settings, http_settings)
        ) as http:
            client = BigKindsClient(source_settings, http)
            summary = open_session.with_options(
                retries=http_settings.retries,
                retry_delay_seconds=http_settings.retry_delay_seconds,
                retry_condition_fn=retry_transient,
            )(client, summary)
            response = fetch(client, request, summary, 1)
            page = normalize_page(response, summary)
            pages.append(page)
            seen_ids = set(page.source_ids)
            page_count = max(1, ceil(page.total_count / request.page_size))
            if request.max_pages is not None:
                page_count = min(page_count, request.max_pages)
            for page_number in range(2, page_count + 1):
                response = fetch(client, request, summary, page_number)
                page = normalize_page(response, summary, frozenset(seen_ids))
                pages.append(page)
                seen_ids.update(page.source_ids)
        result = finish_collection(summary, pages)
        get_run_logger().info(
            "목록 수집 %s: 조회 %s건, 고유 %s건, 중복 %s건, 결과 %s",
            result.status,
            result.retrieved_count,
            result.unique_count,
            result.duplicate_count,
            result.output_directory,
        )
        return result
    except Exception as error:
        retrieved = sum(page.article_count for page in pages)
        unique = len({source_id for page in pages for source_id in page.source_ids})
        failed = summary.model_copy(
            update={
                "status": "failed",
                "finished_at": datetime.now(UTC),
                "pages_collected": len(pages),
                "initial_total_count": pages[0].total_count if pages else None,
                "latest_total_count": pages[-1].total_count if pages else None,
                "retrieved_count": retrieved,
                "unique_count": unique,
                "duplicate_count": retrieved - unique,
                "error_type": type(error).__name__,
            }
        )
        write_model(summary.output_directory / "manifest.json", failed)
        raise
