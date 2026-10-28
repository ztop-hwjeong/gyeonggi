import asyncio
from datetime import UTC, datetime
from uuid import UUID

from playwright.async_api import Error as PlaywrightError
from prefect import flow, get_run_logger, task
from prefect.cache_policies import NO_CACHE
from prefect.context import FlowRunContext

from articles.browser import close_article_tabs
from articles.container import create_detail_container
from articles.models import ArticleDetail, ArticleSeed, DetailAttempt, DetailRunSummary, DetailStage
from articles.pipeline import ArticleDetailCollector, browser_allowed
from articles.requests import RequestStoppedError
from articles.storage import DetailRepository
from config import BrowserFetchSettings


@task(name="collect-article-stage", cache_policy=NO_CACHE, persist_result=False)
def collect_stage(
    stage: DetailStage,
    seed: ArticleSeed,
    run_id: UUID,
) -> DetailAttempt:
    container = create_detail_container()
    try:
        with container() as scoped:
            result = scoped.get(ArticleDetailCollector).attempt(stage, seed, run_id)
    finally:
        container.close()
    get_run_logger().info(
        "기사 %s: %s %s (%s)", seed.source_id, stage, result.status, result.reason
    )
    return result


@task(name="cleanup-article-tabs", cache_policy=NO_CACHE, persist_result=False)
def cleanup_browser_tabs() -> None:
    container = create_detail_container()
    try:
        with container() as scoped:
            settings = scoped.get(BrowserFetchSettings)
            try:
                asyncio.run(close_article_tabs(settings))
            except (RequestStoppedError, PlaywrightError) as error:
                get_run_logger().warning("수집 탭 정리 실패: %s", error)
    finally:
        container.close()


@task(name="finalize-article-detail", cache_policy=NO_CACHE, persist_result=False)
def finish_article(
    seed: ArticleSeed,
    attempts: list[DetailAttempt],
    run_id: UUID,
) -> ArticleDetail:
    selected = next((attempt for attempt in attempts if attempt.status == "accepted"), None)
    skipped = next((attempt for attempt in attempts if attempt.skip_reason is not None), None)
    if selected and selected.extraction and selected.extraction.publisher:
        seed = seed.model_copy(
            update={
                "publisher": selected.extraction.publisher.name,
                "publisher_code": selected.extraction.publisher.code,
            }
        )
    result = ArticleDetail(
        seed=seed,
        status="collected" if selected else "skipped" if skipped else "failed",
        skip_reason=skipped.skip_reason if skipped and not selected else None,
        selected_stage=selected.stage if selected else None,
        attempts=attempts,
    )
    container = create_detail_container()
    try:
        with container() as scoped:
            scoped.get(DetailRepository).save_detail(run_id, result)
    finally:
        container.close()
    return result


@flow(name="collect-article-details", persist_result=False)
def collect_article_details(
    articles: list[ArticleSeed], allow_bigkinds_fallback: bool = True
) -> DetailRunSummary:
    if not articles:
        raise ValueError("상세 수집할 기사 필요")
    identifiers = [article.source_id for article in articles]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("중복된 상세 수집 대상")
    container = create_detail_container()
    try:
        with container() as scoped:
            repository = scoped.get(DetailRepository)
            return run_collection(articles, repository, allow_bigkinds_fallback)
    finally:
        container.close()


@flow(name="collect-naver-news-details", persist_result=False)
def collect_naver_news_details(
    limit: int = 50, search_run_id: UUID | None = None
) -> DetailRunSummary:
    if not 1 <= limit <= 500:
        raise ValueError("네이버 본문 수집 건수는 1~500 범위 필요")
    container = create_detail_container()
    try:
        with container() as scoped:
            repository = scoped.get(DetailRepository)
            articles = repository.pending_naver_news(limit, search_run_id)
            return run_collection(articles, repository, allow_bigkinds_fallback=False)
    finally:
        container.close()


@flow(name="collect-pending-article-details", persist_result=False)
def collect_pending_article_details(limit: int = 50) -> DetailRunSummary:
    if not 1 <= limit <= 500:
        raise ValueError("본문 수집 건수는 1~500 범위 필요")
    container = create_detail_container()
    try:
        with container() as scoped:
            repository = scoped.get(DetailRepository)
            return run_collection(repository.pending_articles(limit), repository)
    finally:
        container.close()


def run_collection(
    articles: list[ArticleSeed],
    repository: DetailRepository,
    allow_bigkinds_fallback: bool = True,
) -> DetailRunSummary:
    context = FlowRunContext.get()
    if context is None or context.flow_run is None:
        raise RuntimeError("Prefect flow 실행 문맥 필요")
    run_id = str(context.flow_run.id)
    summary = DetailRunSummary(
        run_id=run_id,
        status="running",
        started_at=datetime.now(UTC),
        requested_count=len(articles),
    )
    repository.save_run(summary)
    results: list[ArticleDetail] = []
    try:
        cleanup_browser_tabs()
        for seed in articles:
            attempts = [collect_stage("curl_cffi", seed, UUID(run_id))]
            if attempts[-1].status != "accepted" and attempts[-1].skip_reason is None:
                if browser_allowed(attempts[-1]):
                    attempts.append(collect_stage("browser_fetch", seed, UUID(run_id)))
                else:
                    skipped = DetailAttempt(
                        stage="browser_fetch",
                        status="skipped",
                        reason="원문 서버 대기·인증·요청 제한 유지",
                    )
                    attempts.append(skipped)
                    repository.save_attempt(UUID(run_id), seed, skipped)
            if attempts[-1].status not in ("accepted", "skipped") and browser_allowed(attempts[-1]):
                attempts.append(collect_stage("browser_rendered", seed, UUID(run_id)))
            if (
                attempts[-1].status != "accepted"
                and attempts[-1].skip_reason is None
                and allow_bigkinds_fallback
                and seed.source == "bigkinds"
            ):
                attempts.append(collect_stage("bigkinds_api", seed, UUID(run_id)))
            result = finish_article(seed, attempts, UUID(run_id))
            results.append(result)
            summary = update_summary(summary, results, repository, final=False)
        return update_summary(summary, results, repository, final=True)
    except Exception:
        failed = summary.model_copy(update={"status": "failed", "finished_at": datetime.now(UTC)})
        repository.save_run(failed)
        raise
    finally:
        cleanup_browser_tabs()


def update_summary(
    summary: DetailRunSummary,
    results: list[ArticleDetail],
    repository: DetailRepository,
    final: bool,
) -> DetailRunSummary:
    collected = sum(result.status == "collected" for result in results)
    skipped = sum(result.status == "skipped" for result in results)
    failed = sum(result.status == "failed" for result in results)
    result = summary.model_copy(
        update={
            "collected_count": collected,
            "failed_count": failed,
            "skipped_count": skipped,
            "status": ("completed" if failed == 0 else "partial")
            if final
            else "running",
            "finished_at": datetime.now(UTC) if final else None,
        }
    )
    repository.save_run(result)
    return result
