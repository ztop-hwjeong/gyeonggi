import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from articles import browser
from articles.requests import RequestStoppedError
from config import BrowserFetchSettings, DetailSettings


def test_driver_disconnect_is_reported_as_browser_connection_failure():
    playwright = Mock()
    playwright.chromium.connect_over_cdp = AsyncMock(side_effect=Exception("driver disconnected"))
    with pytest.raises(RequestStoppedError, match="브라우저 연결 실패"):
        asyncio.run(
            browser.connect_browser(
                playwright,
                BrowserFetchSettings.model_validate(
                    {
                        "browser_cdp_url": "http://127.0.0.1:9222",
                    }
                ),
            )
        )


@pytest.mark.parametrize("has_other_page", [True, False])
def test_cleanup_closes_only_collector_tabs_and_keeps_window(monkeypatch, has_other_page):
    owned = Mock(
        evaluate=AsyncMock(return_value="collector-article-render:https://example.org"),
        close=AsyncMock(),
    )
    other = Mock(evaluate=AsyncMock(return_value="user-tab"), close=AsyncMock())
    context = Mock(pages=[owned, other] if has_other_page else [owned], new_page=AsyncMock())
    connection = Mock(contexts=[context], close=AsyncMock())
    playwright = Mock()
    playwright.chromium.connect_over_cdp = AsyncMock(return_value=connection)
    manager = MagicMock()
    manager.__aenter__ = AsyncMock(return_value=playwright)
    manager.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(browser, "async_playwright", Mock(return_value=manager))
    asyncio.run(
        browser.close_article_tabs(
            BrowserFetchSettings.model_validate(
                {
                    "browser_cdp_url": "http://127.0.0.1:9222",
                }
            )
        )
    )
    owned.close.assert_awaited_once()
    other.close.assert_not_called()
    assert context.new_page.await_count == (0 if has_other_page else 1)
    connection.close.assert_awaited_once()


@pytest.mark.parametrize("status", [200, 429])
def test_rendered_capture_closes_tab_and_stops_on_wait_response(
    monkeypatch, seed, article_html, status
):
    page = MagicMock()
    page.url = str(seed.original_url)
    page.evaluate = AsyncMock(return_value="collector-article-render:https://example.org")
    page.route = AsyncMock()
    page.unroute = AsyncMock()
    response = Mock(status=status, headers={"retry-after": "120"} if status == 429 else {})
    response.body = AsyncMock(return_value=b"rate limited")
    page.goto = AsyncMock(return_value=response)
    page.wait_for_function = AsyncMock()
    page.content = AsyncMock(return_value=article_html.decode())
    page.close = AsyncMock()
    context = Mock(pages=[Mock(), page], new_page=AsyncMock(return_value=page))
    connection = Mock(contexts=[context], close=AsyncMock())
    playwright = Mock()
    playwright.chromium.connect_over_cdp = AsyncMock(return_value=connection)
    manager = MagicMock()
    manager.__aenter__ = AsyncMock(return_value=playwright)
    manager.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(browser, "async_playwright", Mock(return_value=manager))
    monkeypatch.setattr(browser, "validate_public_url", lambda url: url)
    store = Mock()
    limiter = Mock()
    snapshots = []
    call = browser.fetch_rendered_browser(
        seed,
        store,
        DetailSettings(bigkinds_rate_limit_name="test"),
        BrowserFetchSettings.model_validate({"browser_cdp_url": "http://127.0.0.1:9222"}),
        limiter,
        snapshots,
    )
    if status == 429:
        with pytest.raises(RequestStoppedError):
            asyncio.run(call)
        page.content.assert_not_called()
        page.wait_for_function.assert_not_called()
    else:
        asyncio.run(call)
        assert store.save_response.call_args.args[3] == "application/x-rendered-html; charset=utf-8"
        assert store.save_response.call_args.args[4] == article_html
    assert store.save_response.call_args.args[0] == "browser_rendered"
    assert len(snapshots) == 1
    page.close.assert_awaited_once()
    connection.close.assert_awaited_once()
    page.unroute.assert_awaited_once()

    def deny_private(url):
        raise RequestStoppedError("공개 인터넷 원문 주소 필요")

    monkeypatch.setattr(browser, "validate_public_url", deny_private)
    route = Mock(abort=AsyncMock(), continue_=AsyncMock())
    route.request.is_navigation_request.return_value = True
    route.request.frame = page.main_frame
    route.request.url = "http://127.0.0.1/admin"
    handler = page.route.call_args.args[1]
    asyncio.run(handler(route))
    route.abort.assert_awaited_once()
    route.continue_.assert_not_called()


@pytest.mark.parametrize("stage", ["fetch", "rendered"])
def test_navigation_failure_closes_new_unmarked_page(monkeypatch, seed, stage):
    page = Mock(
        evaluate=AsyncMock(side_effect=RequestStoppedError("표시 실패")),
        close=AsyncMock(),
    )
    context = Mock(pages=[Mock(), page], new_page=AsyncMock(return_value=page))
    connection = Mock(contexts=[context], close=AsyncMock())
    playwright = Mock()
    playwright.chromium.connect_over_cdp = AsyncMock(return_value=connection)
    manager = MagicMock(
        __aenter__=AsyncMock(return_value=playwright), __aexit__=AsyncMock(return_value=False)
    )
    monkeypatch.setattr(browser, "async_playwright", Mock(return_value=manager))
    monkeypatch.setattr(browser, "validate_public_url", lambda url: url)
    fetch = browser.fetch_browser if stage == "fetch" else browser.fetch_rendered_browser
    with pytest.raises(RequestStoppedError, match="표시 실패"):
        asyncio.run(
            fetch(
                seed,
                Mock(),
                DetailSettings(bigkinds_rate_limit_name="test"),
                BrowserFetchSettings.model_validate({"browser_cdp_url": "http://127.0.0.1:9222"}),
                Mock(),
                [],
            )
        )
    page.close.assert_awaited_once()
    connection.close.assert_awaited_once()
    popup = Mock(close=AsyncMock())
    handler = page.on.call_args.args[1]
    asyncio.run(handler(popup))
    popup.close.assert_awaited_once()


def test_closing_last_article_tab_keeps_one_blank_tab():
    page = Mock(close=AsyncMock())
    context = Mock(pages=[page], new_page=AsyncMock())
    connection = Mock(contexts=[context])
    asyncio.run(browser.close_article_page(connection, page))
    context.new_page.assert_awaited_once()
    page.close.assert_awaited_once()
