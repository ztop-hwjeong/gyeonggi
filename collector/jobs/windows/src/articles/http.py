import json
from urllib.parse import urljoin

from collector_http.client import ChromiumHttpClient
from collector_http.config import HttpSettings
from scrapling import Selector

from articles.domains import has_notice_only_text, has_verified_short_official_body
from articles.matching import normalized_text, verify_article
from articles.models import ArticleSeed, ExtractedArticle, FetchSnapshot
from articles.requests import PublisherRateLimiter, RequestStoppedError, validate_public_url
from articles.storage import ArticleStore
from config import DetailSettings, ExtractionSettings

_BIGKINDS_SUMMARY_DEPENDENT_REASONS = frozenset(
    {
        "검증할 요약 문장 부족",
        "요약 문장 일치 부족",
        "목록 요약보다 충분한 본문 필요",
    }
)


def has_official_bigkinds_body(
    seed: ArticleSeed, title: str, text: str, settings: ExtractionSettings, reason: str
) -> bool:
    """공식 상세 API의 독립 본문 검증."""
    normalized_title = normalized_text(title)
    normalized_body = normalized_text(text)
    body_without_title = normalized_body.removeprefix(normalized_title)
    is_title_repetition = bool(normalized_title) and not body_without_title.replace(
        normalized_title, ""
    )
    reasons = frozenset(part.strip() for part in reason.split(";") if part.strip())
    return (
        normalized_title == normalized_text(seed.title)
        and len(body_without_title) >= settings.min_body_chars
        and not is_title_repetition
        and not has_notice_only_text(body_without_title)
        and reasons.issubset(_BIGKINDS_SUMMARY_DEPENDENT_REASONS)
    )


def is_exact_short_bigkinds_detail(
    seed: ArticleSeed, title: str, text: str, settings: ExtractionSettings
) -> bool:
    """빅카인즈 단문 원문과 목록 절단 요약 일치 검증."""
    normalized_title = normalized_text(title)
    normalized_summary = normalized_text(seed.summary)
    normalized_body = normalized_text(text)
    return (
        normalized_title == normalized_text(seed.title)
        and normalized_summary != normalized_title
        and len(normalized_summary) >= settings.min_summary_chars
        and normalized_body != normalized_title
        and normalized_body.startswith(normalized_summary)
    )


def extract_bigkinds_detail(
    seed: ArticleSeed, detail: dict[str, object], settings: ExtractionSettings
) -> ExtractedArticle:
    """저장 원본 재생에도 사용하는 빅카인즈 상세 추출."""
    if detail["NEWS_ID"] != seed.source_id:
        raise RequestStoppedError("빅카인즈 상세 기사 ID 불일치")
    title = str(Selector(content=f"<div>{detail['TITLE']}</div>").get_all_text(strip=True))
    text = str(
        Selector(content=f"<div>{detail['CONTENT']}</div>").get_all_text(separator="\n", strip=True)
    )
    evidence = verify_article(seed, title, text, settings)
    if has_official_bigkinds_body(seed, title, text, settings, evidence.reason):
        # 목록 요약 갱신과 무관한 공식 ID·제목·실본문 검증
        evidence = evidence.model_copy(
            update={"verified": True, "reason": "빅카인즈 공식 기사 ID·제목 일치 및 본문 확인"}
        )
    elif evidence.reason == "검증할 요약 문장 부족" and normalized_text(
        seed.summary
    ) == normalized_text(seed.title) == normalized_text(title):
        # 목록에 제목만 제공된 기사의 상세 API 고유 ID와 동일 제목을 이용한 검증
        evidence = evidence.model_copy(
            update={"verified": True, "reason": "빅카인즈 기사 ID·제목 일치(목록 본문 요약 없음)"}
        )
    elif evidence.reason == "본문 길이 부족; 목록 요약보다 충분한 본문 필요" and (
        is_exact_short_bigkinds_detail(seed, title, text, settings)
        or has_verified_short_official_body(seed, title, text, settings)
    ):
        evidence = evidence.model_copy(
            update={"verified": True, "reason": "빅카인즈 단문 원문·목록 요약 일치"}
        )
    return ExtractedArticle(title=title, text=text, method="bigkinds_api", evidence=evidence)


def fetch_original(
    seed: ArticleSeed,
    store: ArticleStore,
    settings: DetailSettings,
    http_settings: HttpSettings,
    limiter: PublisherRateLimiter,
    snapshots: list[FetchSnapshot],
) -> FetchSnapshot:
    if seed.original_url is None:
        raise RequestStoppedError("원문 URL 없음")
    url = str(seed.original_url)
    with ChromiumHttpClient(http_settings, lambda: limiter.acquire(url)) as http:
        for _ in range(settings.max_redirects + 1):
            validate_public_url(url)
            response = http.request_raw("GET", url)
            snapshot = store.save_response(
                "curl_cffi",
                url,
                response.status_code,
                response.headers.get("Content-Type", ""),
                response.content,
                response.headers.get("Retry-After"),
            )
            snapshots.append(snapshot)
            if len(response.content) > settings.max_response_bytes:
                raise RequestStoppedError("원문 응답 크기 제한 초과")
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                if not location:
                    raise RequestStoppedError("리다이렉트 목적지 없음")
                url = urljoin(url, location)
                continue
            if not 200 <= response.status_code < 300:
                raise RequestStoppedError(f"원문 HTTP {response.status_code}")
            if snapshot.retry_after is not None:
                raise RequestStoppedError("원문 서버의 대기 요청")
            return snapshot
    raise RequestStoppedError("원문 리다이렉트 횟수 제한 초과")


def fetch_bigkinds(
    seed: ArticleSeed,
    store: ArticleStore,
    settings: DetailSettings,
    http_settings: HttpSettings,
    limiter: PublisherRateLimiter,
    extraction_settings: ExtractionSettings,
    snapshots: list[FetchSnapshot],
) -> ExtractedArticle:
    if seed.source != "bigkinds":
        raise RequestStoppedError("빅카인즈 상세는 빅카인즈 기사 ID 필요")
    base = str(settings.bigkinds_base_url).rstrip("/")
    with ChromiumHttpClient(http_settings, limiter.acquire_bigkinds) as http:
        warmup = http.request_raw("GET", base + "/v2/news/search.do")
        snapshot = store.save_response(
            "bigkinds_api",
            base + "/v2/news/search.do",
            warmup.status_code,
            warmup.headers.get("Content-Type", ""),
            warmup.content,
            warmup.headers.get("Retry-After"),
        )
        snapshots.append(snapshot)
        if warmup.status_code != 200 or snapshot.retry_after is not None:
            raise RequestStoppedError(f"빅카인즈 세션 초기화 HTTP {warmup.status_code}")
        response = http.request_raw(
            "GET",
            base + "/news/detailView.do",
            params={
                "docId": seed.source_id,
                "returnCnt": 1,
                "sectionDiv": "1000",
            },
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Referer": base + "/v2/news/search.do",
                "X-Requested-With": "XMLHttpRequest",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
            },
        )
    snapshot = store.save_response(
        "bigkinds_api",
        base + "/news/detailView.do",
        response.status_code,
        response.headers.get("Content-Type", ""),
        response.content,
        response.headers.get("Retry-After"),
    )
    snapshots.append(snapshot)
    if not 200 <= response.status_code < 300 or snapshot.retry_after is not None:
        raise RequestStoppedError(f"빅카인즈 상세 HTTP {response.status_code}")
    if len(response.content) > settings.max_response_bytes:
        raise RequestStoppedError("빅카인즈 상세 응답 크기 제한 초과")
    data = json.loads(response.content)
    detail = data["detail"]
    if not isinstance(detail, dict):
        raise ValueError("빅카인즈 상세 형식 오류")
    return extract_bigkinds_detail(seed, detail, extraction_settings)
