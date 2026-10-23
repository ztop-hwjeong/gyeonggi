from playwright.async_api import BrowserContext, Response, async_playwright

from config import BrowserFetchSettings
from sources.naver_cafe.models import CafeTarget


class NavigationStopped(ValueError):
    def __init__(self, response: Response) -> None:
        super().__init__("카페 페이지 접근 제한")
        self.response = response


async def capture_article(
    context: BrowserContext, target: CafeTarget, settings: BrowserFetchSettings
) -> Response:
    marker = "collector-naver-cafe-detail"
    page = None
    for candidate in context.pages:
        if (
            candidate.url.startswith("https://cafe.naver.com/")
            and await candidate.evaluate("window.name") == marker
        ):
            page = candidate
            break
    if page is None:
        page = await context.new_page()
        await page.evaluate("name => {window.name = name}", marker)
    # 글 이동 전에 감시를 시작해 초기 상세 응답의 유실 방지
    async with page.expect_response(
        lambda response: target.matches_response(response.url),
        timeout=settings.browser_fetch_timeout_ms,
    ) as captured:
        navigation = await page.goto(
            target.url,
            wait_until="domcontentloaded",
            timeout=settings.browser_navigation_timeout_ms,
        )
        if navigation is not None and navigation.status in (401, 403, 429):
            raise NavigationStopped(navigation)
    await page.evaluate("name => {window.name = name}", marker)
    return await captured.value


async def collect_response(
    target: CafeTarget, settings: BrowserFetchSettings, max_bytes: int
) -> tuple[str, int, dict[str, str], bytes]:
    async with async_playwright() as playwright:
        connection = await playwright.chromium.connect_over_cdp(
            str(settings.browser_cdp_url), timeout=settings.browser_connect_timeout_ms
        )
        try:
            try:
                response = await capture_article(connection.contexts[0], target, settings)
            except NavigationStopped as stopped:
                response = stopped.response
            body = await response.body()
            if len(body) > max_bytes:
                raise ValueError("카페 상세 응답 크기 제한 초과")
            headers = await response.all_headers()
            # 인증·쿠키 헤더를 저장 경로로 전달하지 않는 응답 메타데이터 제한
            selected = {
                key: headers[key] for key in ("content-type", "retry-after") if key in headers
            }
            return response.url.split("?")[0], response.status, selected, body
        finally:
            # 전용 탭과 Edge 창은 유지하고 자동화 연결만 해제
            await connection.close()
