import asyncio
from uuid import UUID

from collector_http.client import TransientHttpError
from collector_http.config import HttpSettings
from curl_cffi.requests.exceptions import RequestException
from playwright.async_api import Error as PlaywrightError

from articles.browser import fetch_browser, fetch_rendered_browser
from articles.extraction import ArticleExtractor, ExtractionRejectedError, NoTextBodyError
from articles.http import fetch_bigkinds, fetch_original
from articles.models import ArticleSeed, DetailAttempt, DetailStage, ExtractedArticle, FetchSnapshot
from articles.requests import PublisherRateLimiter, RequestStoppedError
from articles.storage import ArticleStore, DetailRepository
from config import BrowserFetchSettings, DetailSettings, ExtractionSettings


class ArticleDetailCollector:
    def __init__(
        self,
        settings: DetailSettings,
        http_settings: HttpSettings,
        browser_settings: BrowserFetchSettings,
        extraction_settings: ExtractionSettings,
        repository: DetailRepository,
    ) -> None:
        self._settings = settings
        self._http = http_settings
        self._browser = browser_settings
        self._extraction = extraction_settings
        self._repository = repository
        self._extractor = ArticleExtractor(repository, extraction_settings)
        self._limiter = PublisherRateLimiter(settings)

    def attempt(self, stage: DetailStage, seed: ArticleSeed, run_id: UUID) -> DetailAttempt:
        store = ArticleStore(self._repository, run_id, seed)
        snapshots: list[FetchSnapshot] = []
        try:
            if stage == "curl_cffi":
                snapshot = fetch_original(
                    seed, store, self._settings, self._http, self._limiter, snapshots
                )
                extraction = self._extractor.extract(
                    seed, self._repository.read_body(snapshot), snapshot.url, snapshot.content_type
                )
            elif stage in ("browser_fetch", "browser_rendered"):
                fetch = fetch_browser if stage == "browser_fetch" else fetch_rendered_browser
                snapshot = asyncio.run(
                    fetch(seed, store, self._settings, self._browser, self._limiter, snapshots)
                )
                extraction = self._extractor.extract(
                    seed, self._repository.read_body(snapshot), snapshot.url, snapshot.content_type
                )
            else:
                extraction = fetch_bigkinds(
                    seed,
                    store,
                    self._settings,
                    self._http,
                    self._limiter,
                    self._extraction,
                    snapshots,
                )
            result = self._result(stage, extraction, snapshots)
        except NoTextBodyError as error:
            confirmed = stage == "browser_rendered"
            result = DetailAttempt(
                stage=stage,
                status="skipped" if confirmed else "rejected",
                skip_reason="no_text_body" if confirmed else None,
                reason=str(error),
                snapshots=snapshots,
            )
        except (
            RequestStoppedError,
            TransientHttpError,
            RequestException,
            PlaywrightError,
            ExtractionRejectedError,
            ValueError,
            KeyError,
            OSError,
        ) as error:
            result = DetailAttempt(
                stage=stage,
                status="failed",
                reason=f"{type(error).__name__}: {error}",
                snapshots=snapshots,
            )
        self._repository.save_attempt(run_id, seed, result)
        return result

    @staticmethod
    def _result(
        stage: DetailStage, extraction: ExtractedArticle, snapshots: list[FetchSnapshot]
    ) -> DetailAttempt:
        return DetailAttempt(
            stage=stage,
            status="accepted" if extraction.evidence.verified else "rejected",
            reason=extraction.evidence.reason,
            snapshots=snapshots,
            extraction=extraction,
        )


def browser_allowed(attempt: DetailAttempt) -> bool:
    # 서버의 대기 지시를 다른 전송 방식으로 반복하지 않는 요청 제어
    return (
        not any(
            snapshot.status_code in (401, 429) or snapshot.retry_after is not None
            for snapshot in attempt.snapshots
        )
        and "요청 속도 제한 비활성" not in attempt.reason
    )
