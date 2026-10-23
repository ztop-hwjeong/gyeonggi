from typing import cast
from unittest.mock import Mock

import pytest
from collector_http import client
from collector_http.client import AccessRestrictedError, ChromiumHttpClient, TransientHttpError
from collector_http.config import HttpSettings
from curl_cffi import requests


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch) -> Mock:
    session = Mock(spec=requests.Session)
    response = Mock(spec=requests.Response)
    response.status_code = 200
    response.headers = {"Content-Type": "application/json"}
    response.text = "{}"
    session.request.return_value = response
    monkeypatch.setattr(client.requests, "Session", Mock(return_value=session))
    return session


def test_uses_chromium_fingerprint_and_releases_session(session: Mock) -> None:
    acquire = Mock()
    settings = HttpSettings()
    with ChromiumHttpClient(settings, acquire) as http:
        http.request("GET", "https://example.org")
    cast(Mock, client.requests.Session).assert_called_once_with(
        impersonate="chrome", default_headers=True, timeout=30, allow_redirects=False
    )
    acquire.assert_called_once()
    session.close.assert_called_once()


@pytest.mark.parametrize("status", [401, 403, 429])
def test_restriction_stops_without_retry(session: Mock, status: int) -> None:
    session.request.return_value.status_code = status
    with ChromiumHttpClient(HttpSettings(), Mock()) as http:
        with pytest.raises(AccessRestrictedError):
            http.request("GET", "https://example.org")
    session.request.assert_called_once()


def test_retry_after_stops_requests(session: Mock) -> None:
    session.request.return_value.headers["Retry-After"] = "120"
    with ChromiumHttpClient(HttpSettings(), Mock()) as http:
        with pytest.raises(AccessRestrictedError, match="대기 요청"):
            http.request("GET", "https://example.org")


def test_success_status_challenge_is_not_accepted(session: Mock) -> None:
    session.request.return_value.headers = {"Content-Type": "text/html"}
    session.request.return_value.text = "<html>Verify you are human</html>"
    with ChromiumHttpClient(HttpSettings(), Mock()) as http:
        with pytest.raises(AccessRestrictedError):
            http.request("GET", "https://example.org")


@pytest.mark.parametrize(
    "error", [requests.exceptions.Timeout, requests.exceptions.ConnectionError]
)
def test_connection_errors_are_retryable(session: Mock, error: type[Exception]) -> None:
    session.request.side_effect = error("failed")
    with ChromiumHttpClient(HttpSettings(), Mock()) as http:
        with pytest.raises(TransientHttpError):
            http.request("GET", "https://example.org")


def test_server_errors_are_retryable(session: Mock) -> None:
    session.request.return_value.status_code = 503
    with ChromiumHttpClient(HttpSettings(), Mock()) as http:
        with pytest.raises(TransientHttpError):
            http.request("GET", "https://example.org")


def test_missing_rate_limiter_prevents_network_request(session: Mock) -> None:
    acquire = Mock(side_effect=RuntimeError("limit missing"))
    with ChromiumHttpClient(HttpSettings(), acquire) as http:
        with pytest.raises(RuntimeError, match="limit missing"):
            http.request("GET", "https://example.org")
    session.request.assert_not_called()
