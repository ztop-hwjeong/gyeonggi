import asyncio
from uuid import UUID

from playwright.async_api import Error as PlaywrightError
from prefect.client.orchestration import get_client
from prefect.client.schemas.actions import GlobalConcurrencyLimitCreate
from prefect.concurrency.sync import rate_limit
from prefect.exceptions import ObjectAlreadyExists, ObjectNotFound

from articles.models import ArticleSeed, DetailAttempt, FetchSnapshot
from articles.storage import ArticleStore, DetailRepository
from config import BrowserFetchSettings
from sources.naver_cafe.browser import collect_response
from sources.naver_cafe.extraction import extract_article
from sources.naver_cafe.models import CafeSettings, CafeTarget


def acquire_navigation(settings: CafeSettings) -> None:
    name = settings.rate_limit_name
    with get_client(sync_client=True) as client:
        try:
            limit = client.read_global_concurrency_limit_by_name(name)
        except ObjectNotFound:
            try:
                client.create_global_concurrency_limit(
                    GlobalConcurrencyLimitCreate(
                        name=name,
                        limit=1,
                        slot_decay_per_second=1 / settings.request_interval_seconds,
                    )
                )
            except ObjectAlreadyExists:
                pass
            limit = client.read_global_concurrency_limit_by_name(name)
    if not limit.active or limit.limit != 1 or limit.slot_decay_per_second <= 0:
        raise RuntimeError("카페 요청 속도 제한 비활성 또는 설정 오류")
    rate_limit(name, timeout_seconds=settings.rate_limit_timeout_seconds, strict=True)


def collect_article(
    seed: ArticleSeed,
    run_id: UUID,
    repository: DetailRepository,
    settings: CafeSettings,
    browser: BrowserFetchSettings,
) -> DetailAttempt:
    snapshots: list[FetchSnapshot] = []
    try:
        if seed.source != "naver_cafearticle" or seed.original_url is None:
            raise ValueError("카페 상세 수집 대상 필요")
        target = CafeTarget.from_url(str(seed.original_url))
        acquire_navigation(settings)
        url, status, headers, body = asyncio.run(
            collect_response(target, browser, settings.max_response_bytes)
        )
        snapshot = ArticleStore(repository, run_id, seed).save_response(
            "browser_fetch",
            url,
            status,
            headers.get("content-type", ""),
            body,
            headers.get("retry-after"),
        )
        snapshots.append(snapshot)
        if status != 200 or snapshot.retry_after is not None:
            raise ValueError("카페 상세 접근 제한 또는 비정상 HTTP 응답")
        extraction = extract_article(body, target, seed, settings.title_similarity)
        attempt = DetailAttempt(
            stage="browser_fetch",
            status="accepted" if extraction.evidence.verified else "rejected",
            reason=extraction.evidence.reason,
            snapshots=snapshots,
            extraction=extraction,
        )
    except (PlaywrightError, ValueError, KeyError, TypeError, OSError) as error:
        attempt = DetailAttempt(
            stage="browser_fetch",
            status="failed",
            reason=f"카페 상세 수집 실패: {type(error).__name__}",
            snapshots=snapshots,
        )
    repository.save_attempt(run_id, seed, attempt)
    return attempt
