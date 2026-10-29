import asyncio
from datetime import UTC, date, datetime
from functools import partial
from uuid import UUID

from collector_http.client import ChromiumHttpClient
from curl_cffi.requests import Response
from prefect import flow
from prefect.context import FlowRunContext

from sources.blogs.container import create_blog_container
from sources.blogs.extraction import decode_blog_html, extract_blog
from sources.blogs.http import fetch_blog
from sources.blogs.models import BlogSeed
from sources.blogs.storage import BlogDetailRepository


def blog_seed(item: dict) -> BlogSeed:
    return BlogSeed.model_validate(
        {
            "source": item["source"],
            "source_id": item["source_id"],
            "url": item["url"],
            "title": item["title"],
            "summary": item.get("summary", ""),
            "published_on": item.get("published_on"),
        }
    )


def terminal_skip_reason(error: Exception) -> str | None:
    reason = str(error)
    if reason == "텍스트 본문 부족":
        return "no_text_body"
    if reason == "블로그 비공개" or reason.endswith(("HTTP 404", "HTTP 410")):
        return "unavailable"
    return None


def save_blog_response(
    repository: BlogDetailRepository,
    run_id: UUID,
    seed_data: dict,
    snapshots: list[dict],
    stage: str,
    url: str,
    response: Response,
) -> None:
    snapshots.append(
        repository.save_response(
            run_id,
            seed_data,
            stage,
            url,
            response.status_code,
            response.headers.get("Content-Type", ""),
            response.content,
            response.headers.get("Retry-After"),
        )
    )


@flow(name="collect-pending-blog-details", persist_result=False)
def collect_pending_blog_details(
    limit: int = 50,
    start_date: date | None = None,
    search_run_id: str | None = None,
    retry_source_ids: list[str] | None = None,
) -> dict:
    if not 1 <= limit <= 500:
        raise ValueError("블로그 본문 수집 건수는 1~500 범위 필요")
    context = FlowRunContext.get()
    if context is None or context.flow_run is None:
        raise RuntimeError("Prefect flow 실행 문맥 필요")
    run_id = context.flow_run.id
    container = create_blog_container()
    summary = {
        "status": "running",
        "started_at": datetime.now(UTC).isoformat(),
        "requested_count": 0,
    }
    try:
        with container() as scoped:
            repository = scoped.get(BlogDetailRepository)
            http = scoped.get(ChromiumHttpClient)
            seeds = [
                blog_seed(item)
                for item in repository.pending_blog_sources(
                    limit,
                    start_date,
                    UUID(search_run_id) if search_run_id else None,
                    retry_source_ids,
                )
            ]
            summary["requested_count"] = len(seeds)
            repository.save_run(run_id, summary)
            counts = {"collected": 0, "failed": 0, "skipped": 0}
            interrupted = None
            try:
                for seed in seeds:
                    seed_data = seed.model_dump(mode="json")
                    snapshots = []

                    try:
                        _url, _body, content_type = fetch_blog(
                            http,
                            seed,
                            partial(save_blog_response, repository, run_id, seed_data, snapshots),
                        )
                        markup = decode_blog_html(repository.read_body(snapshots[-1]), content_type)
                        extraction, evidence = extract_blog(markup, seed)
                        repository.save_result(
                            run_id,
                            seed_data,
                            {"status": "collected", "reason": evidence["reason"]},
                            extraction.model_dump(mode="json")
                            | {
                                "stage": "html",
                                "provenance": {
                                    "snapshots": snapshots,
                                    "evidence": evidence,
                                    "content_type": content_type,
                                },
                            },
                        )
                        counts["collected"] += 1
                    except Exception as error:
                        skip_reason = terminal_skip_reason(error)
                        status = "skipped" if skip_reason else "failed"
                        repository.save_result(
                            run_id,
                            seed_data,
                            {
                                "status": status,
                                "skip_reason": skip_reason,
                                "reason": f"{type(error).__name__}: {error}",
                            },
                        )
                        counts[status] += 1
            except BaseException as error:
                interrupted = (
                    "cancelled"
                    if isinstance(error, (KeyboardInterrupt, asyncio.CancelledError))
                    else "failed"
                )
                raise
            finally:
                summary.update(
                    status=interrupted or ("completed" if counts["failed"] == 0 else "partial"),
                    finished_at=datetime.now(UTC).isoformat(),
                    collected_count=counts["collected"],
                    failed_count=counts["failed"],
                    skipped_count=counts["skipped"],
                )
                repository.save_run(run_id, summary)
            return summary
    finally:
        container.close()
