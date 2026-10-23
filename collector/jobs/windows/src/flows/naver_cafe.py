from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import cast
from uuid import UUID

from collector_storage.config import DatabaseSettings, ObjectStorageSettings
from collector_storage.objects import ObjectCredentials, RawObjectStore
from prefect import flow, task
from prefect.blocks.system import Secret
from prefect.cache_policies import NO_CACHE
from prefect.context import FlowRunContext
from pydantic import SecretStr

from articles.models import ArticleDetail, ArticleSeed, DetailAttempt, DetailRunSummary
from articles.storage import DetailRepository
from config import BrowserFetchSettings
from flows.details import finish_article, update_summary
from sources.naver_cafe.collection import collect_article
from sources.naver_cafe.models import CafeSettings
from sources.naver_cafe.queue import CafeQueue


@task(name="collect-naver-cafe-article", cache_policy=NO_CACHE, persist_result=False, retries=0)
def collect_one(
    seed: ArticleSeed,
    run_id: UUID,
    repository: DetailRepository,
    settings: CafeSettings,
    browser: BrowserFetchSettings,
) -> DetailAttempt:
    return collect_article(seed, run_id, repository, settings, browser)


def pause_seconds(attempt: DetailAttempt, settings: CafeSettings) -> float | None:
    for snapshot in attempt.snapshots:
        if snapshot.status_code in (401, 403, 429) or snapshot.retry_after is not None:
            seconds = float(settings.error_pause_seconds)
            if snapshot.retry_after:
                try:
                    seconds = max(seconds, float(snapshot.retry_after))
                except ValueError:
                    try:
                        seconds = max(
                            seconds,
                            (
                                parsedate_to_datetime(snapshot.retry_after) - datetime.now(UTC)
                            ).total_seconds(),
                        )
                    except (ValueError, TypeError):
                        pass
            return seconds
    return None


def run_batch(
    repository: DetailRepository,
    settings: CafeSettings,
    browser: BrowserFetchSettings,
    run_id: UUID,
) -> DetailRunSummary:
    queue = CafeQueue(repository, settings)
    summary = DetailRunSummary(
        run_id=str(run_id), status="running", started_at=datetime.now(UTC), requested_count=0
    )
    repository.save_run(summary)
    results: list[ArticleDetail] = []
    try:
        with queue.batch() as seeds:
            summary.requested_count = len(seeds)
            repository.save_run(summary)
            for seed in seeds:
                attempt = collect_one(seed, run_id, repository, settings, browser)
                results.append(finish_article(seed, [attempt], summary, repository))
                summary = update_summary(summary, results, repository, final=False)
                if (seconds := pause_seconds(attempt, settings)) is not None:
                    queue.pause(seconds)
                    break
        return update_summary(summary, results, repository, final=True)
    except Exception:
        repository.save_run(
            summary.model_copy(update={"status": "failed", "finished_at": datetime.now(UTC)})
        )
        raise


@flow(name="collect-naver-cafe-details", persist_result=False)
def collect_naver_cafe_details(batch_size: int | None = None) -> DetailRunSummary:
    context = FlowRunContext.get()
    if context is None or context.flow_run is None:
        raise RuntimeError("Prefect flow 실행 문맥 필요")
    database = DatabaseSettings.model_validate({})
    storage = ObjectStorageSettings.model_validate({})
    password = cast(Secret, Secret.load(database.database_password_block)).get()
    credentials = cast(Secret, Secret.load(storage.credentials_block)).get()
    settings = CafeSettings.model_validate(
        {"batch_size": batch_size} if batch_size is not None else {}
    )
    with RawObjectStore(storage, ObjectCredentials.model_validate(credentials)) as objects:
        repository = DetailRepository(database, SecretStr(cast(str, password)), objects)
        return run_batch(
            repository, settings, BrowserFetchSettings.model_validate({}), context.flow_run.id
        )
