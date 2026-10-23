import asyncio
import base64
from urllib.parse import urlsplit

from playwright.async_api import Page, Route, async_playwright

from articles.models import ArticleSeed, FetchSnapshot
from articles.requests import PublisherRateLimiter, RequestStoppedError, validate_public_url
from articles.storage import ArticleStore
from config import BrowserFetchSettings, DetailSettings


async def fetch_in_page(page: Page, url: str, timeout_ms: int, max_bytes: int) -> dict:
    return await page.evaluate(
        """async ({url, timeout, maxBytes}) => {
            const response = await fetch(url, {
                credentials: 'include', redirect: 'error',
                signal: AbortSignal.timeout(timeout)
            });
            const bytes = new Uint8Array(await response.arrayBuffer());
            if (bytes.length > maxBytes) throw new Error('Response too large');
            let binary = '';
            for (let offset = 0; offset < bytes.length; offset += 8192)
                binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
            return {
                url: response.url, status: response.status,
                content_type: response.headers.get('content-type') || '',
                retry_after: response.headers.get('retry-after'), body: btoa(binary)
            };
        }""",
        {"url": url, "timeout": timeout_ms, "maxBytes": max_bytes},
    )


async def fetch_browser(
    seed: ArticleSeed,
    store: ArticleStore,
    settings: DetailSettings,
    browser: BrowserFetchSettings,
    limiter: PublisherRateLimiter,
    snapshots: list[FetchSnapshot],
) -> FetchSnapshot:
    if seed.original_url is None:
        raise RequestStoppedError("원문 URL 없음")
    url = validate_public_url(str(seed.original_url))
    parsed = urlsplit(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    marker = "collector-article-fetch:" + origin
    async with async_playwright() as playwright:
        connection = await playwright.chromium.connect_over_cdp(
            str(browser.browser_cdp_url), timeout=browser.browser_connect_timeout_ms
        )
        try:
            context = connection.contexts[0]
            selected = None
            for page in context.pages:
                if (
                    page.url.startswith(origin + "/")
                    and await page.evaluate("window.name") == marker
                ):
                    selected = page
                    break
            if selected is None:
                selected = await context.new_page()
                await asyncio.to_thread(limiter.acquire, origin)
                response = await selected.goto(
                    origin,
                    wait_until="domcontentloaded",
                    timeout=browser.browser_navigation_timeout_ms,
                )
                if response is None or not 200 <= response.status < 300:
                    raise RequestStoppedError("언론사 출처 탭 준비 실패")
                selected_origin = urlsplit(selected.url)
                if (selected_origin.scheme, selected_origin.netloc) != (
                    parsed.scheme,
                    parsed.netloc,
                ):
                    raise RequestStoppedError("언론사 출처 탭 리다이렉트")
                await selected.evaluate("name => {window.name = name}", marker)
            await asyncio.to_thread(limiter.acquire, url)
            result = await fetch_in_page(
                selected, url, browser.browser_fetch_timeout_ms, settings.max_response_bytes
            )
            snapshot = store.save_response(
                "browser_fetch",
                result["url"],
                result["status"],
                result["content_type"],
                base64.b64decode(result["body"], validate=True),
                result["retry_after"],
            )
            snapshots.append(snapshot)
            if not 200 <= snapshot.status_code < 300 or snapshot.retry_after is not None:
                raise RequestStoppedError(f"브라우저 원문 HTTP {snapshot.status_code}")
            return snapshot
        finally:
            # 관리 중인 Edge와 출처별 탭은 유지하고 CDP 연결만 해제
            await connection.close()


async def fetch_rendered_browser(
    seed: ArticleSeed,
    store: ArticleStore,
    settings: DetailSettings,
    browser: BrowserFetchSettings,
    limiter: PublisherRateLimiter,
    snapshots: list[FetchSnapshot],
) -> FetchSnapshot:
    if seed.original_url is None:
        raise RequestStoppedError("원문 URL 없음")
    url = validate_public_url(str(seed.original_url))
    origin = urlsplit(url)
    marker = f"collector-article-render:{origin.scheme}://{origin.netloc}"
    async with async_playwright() as playwright:
        connection = await playwright.chromium.connect_over_cdp(
            str(browser.browser_cdp_url), timeout=browser.browser_connect_timeout_ms
        )
        try:
            context = connection.contexts[0]
            page = None
            for candidate in context.pages:
                if (
                    candidate.url.startswith(("http://", "https://"))
                    and await candidate.evaluate("window.name") == marker
                ):
                    page = candidate
                    break
            if page is None:
                page = await context.new_page()
            selected = page
            navigations = 0

            async def check_navigation(route: Route) -> None:
                nonlocal navigations
                if (
                    route.request.is_navigation_request()
                    and route.request.frame == selected.main_frame
                ):
                    navigations += 1
                    try:
                        await asyncio.to_thread(validate_public_url, route.request.url)
                    except RequestStoppedError:
                        await route.abort()
                        return
                    if navigations > settings.max_redirects + 1:
                        await route.abort()
                        return
                await route.continue_()

            await selected.route("**/*", check_navigation)
            try:
                await asyncio.to_thread(limiter.acquire, url)
                response = await selected.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=browser.browser_navigation_timeout_ms,
                )
                if response is None:
                    raise RequestStoppedError("기사 이동 응답 없음")
                await selected.evaluate("name => {window.name = name}", marker)
                retry_after = response.headers.get("retry-after")
                if response.status != 200 or retry_after is not None:
                    snapshot = store.save_response(
                        "browser_rendered",
                        selected.url,
                        response.status,
                        response.headers.get("content-type", ""),
                        await response.body(),
                        retry_after,
                    )
                    snapshots.append(snapshot)
                    raise RequestStoppedError(f"기사 이동 HTTP {response.status}")
                # 제목 태그가 없는 구형 기사 화면까지 포함한 문서 로드 대기
                await selected.wait_for_function(
                    """() => document.readyState === 'complete' &&
                        (document.body?.innerText.length || 0) > 200""",
                    timeout=browser.browser_navigation_timeout_ms,
                )
                body = (await selected.content()).encode("utf-8")
                if len(body) > settings.max_response_bytes:
                    raise RequestStoppedError("렌더링 문서 크기 제한 초과")
                snapshot = store.save_response(
                    "browser_rendered",
                    selected.url,
                    response.status,
                    "application/x-rendered-html; charset=utf-8",
                    body,
                )
                snapshots.append(snapshot)
                return snapshot
            finally:
                await selected.unroute("**/*", check_navigation)
        finally:
            await connection.close()
