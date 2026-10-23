from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from collector_http.config import HttpSettings
from collector_storage.config import DatabaseSettings, ObjectStorageSettings
from collector_storage.objects import ObjectCredentials, RawObjectStore
from prefect import flow, get_run_logger, task
from prefect.blocks.system import Secret
from prefect.cache_policies import NO_CACHE
from prefect.context import FlowRunContext
from pydantic import SecretStr

from articles.models import ArticleDetail, ArticleSeed, DetailAttempt, DetailRunSummary, DetailStage
from articles.pipeline import ArticleDetailCollector, browser_allowed
from articles.storage import DetailRepository
from config import (
    BrowserFetchSettings,
    DetailSettings,
    ExtractionSettings,
)


@task(name="collect-article-stage", cache_policy=NO_CACHE, persist_result=False)
def collect_stage(
    collector: ArticleDetailCollector,
    stage: DetailStage,
    seed: ArticleSeed,
    summary: DetailRunSummary,
) -> DetailAttempt:
    result = collector.attempt(stage, seed, UUID(summary.run_id))
    get_run_logger().info(
        "기사 %s: %s %s (%s)", seed.source_id, stage, result.status, result.reason
    )
    return result


@task(name="finalize-article-detail", cache_policy=NO_CACHE, persist_result=False)
def finish_article(
    seed: ArticleSeed,
    attempts: list[DetailAttempt],
    summary: DetailRunSummary,
    repository: DetailRepository,
) -> ArticleDetail:
    selected = next((attempt for attempt in attempts if attempt.status == "accepted"), None)
    result = ArticleDetail(
        seed=seed,
        status="collected" if selected else "failed",
        selected_stage=selected.stage if selected else None,
        attempts=attempts,
    )
    repository.save_detail(UUID(summary.run_id), result)
    return result


@flow(name="collect-article-details", persist_result=False)
def collect_article_details(
    articles: list[ArticleSeed], allow_bigkinds_fallback: bool = True
) -> DetailRunSummary:
    if not articles:
        raise ValueError("상세 수집할 기사 필요")
    if any(article.source != "bigkinds" for article in articles):
        raise ValueError("빅카인즈 기사 전용 흐름")
    identifiers = [(article.source, article.source_id) for article in articles]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("중복된 상세 수집 대상")
    settings = DetailSettings.model_validate({})
    database = DatabaseSettings.model_validate({})
    block = cast(Secret, Secret.load(database.database_password_block))
    storage_settings = ObjectStorageSettings.model_validate({})
    credentials = cast(Secret, Secret.load(storage_settings.credentials_block))
    with RawObjectStore(
        storage_settings, ObjectCredentials.model_validate(credentials.get())
    ) as objects:
        repository = DetailRepository(database, SecretStr(cast(str, block.get())), objects)
        return run_collection(articles, settings, repository, allow_bigkinds_fallback)


def run_collection(
    articles: list[ArticleSeed],
    settings: DetailSettings,
    repository: DetailRepository,
    allow_bigkinds_fallback: bool = True,
) -> DetailRunSummary:
    collector = ArticleDetailCollector(
        settings,
        HttpSettings(),
        BrowserFetchSettings.model_validate({}),
        ExtractionSettings(),
        repository,
    )
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
        for seed in articles:
            attempts = [collect_stage(collector, "curl_cffi", seed, summary)]
            if attempts[-1].status != "accepted":
                if browser_allowed(attempts[-1]):
                    attempts.append(collect_stage(collector, "browser_fetch", seed, summary))
                else:
                    skipped = DetailAttempt(
                        stage="browser_fetch",
                        status="skipped",
                        reason="원문 서버 대기·인증·요청 제한 유지",
                    )
                    attempts.append(skipped)
                    repository.save_attempt(UUID(run_id), seed, skipped)
            if attempts[-1].status not in ("accepted", "skipped") and browser_allowed(attempts[-1]):
                attempts.append(collect_stage(collector, "browser_rendered", seed, summary))
            if attempts[-1].status != "accepted" and allow_bigkinds_fallback:
                attempts.append(collect_stage(collector, "bigkinds_api", seed, summary))
            result = finish_article(seed, attempts, summary, repository)
            results.append(result)
            summary = update_summary(summary, results, repository, final=False)
        return update_summary(summary, results, repository, final=True)
    except Exception:
        failed = summary.model_copy(update={"status": "failed", "finished_at": datetime.now(UTC)})
        repository.save_run(failed)
        raise


def update_summary(
    summary: DetailRunSummary,
    results: list[ArticleDetail],
    repository: DetailRepository,
    final: bool,
) -> DetailRunSummary:
    collected = sum(result.status == "collected" for result in results)
    result = summary.model_copy(
        update={
            "collected_count": collected,
            "failed_count": len(results) - collected,
            "status": ("completed" if collected == len(results) else "partial")
            if final
            else "running",
            "finished_at": datetime.now(UTC) if final else None,
        }
    )
    repository.save_run(result)
    return result
