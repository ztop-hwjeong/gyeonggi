from collections.abc import Callable
from types import TracebackType
from typing import Any, Self

from curl_cffi import requests
from curl_cffi.requests.session import HttpMethod

from collector_http.config import HttpSettings


class AccessRestrictedError(RuntimeError):
    pass


class TransientHttpError(RuntimeError):
    pass


class UnexpectedResponseError(RuntimeError):
    pass


class ChromiumHttpClient:
    def __init__(self, settings: HttpSettings, acquire_request: Callable[[], None]) -> None:
        self._acquire_request = acquire_request
        self._session = requests.Session(
            impersonate=settings.impersonate,
            default_headers=True,
            timeout=settings.timeout_seconds,
            allow_redirects=False,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._session.close()

    def request_raw(self, method: HttpMethod, url: str, **kwargs: Any) -> requests.Response:
        self._acquire_request()
        try:
            response = self._session.request(method, url, **kwargs)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as error:
            raise TransientHttpError("외부 요청 연결·시간 초과") from error
        return response

    def request(self, method: HttpMethod, url: str, **kwargs: Any) -> requests.Response:
        response = self.request_raw(method, url, **kwargs)
        if response.status_code in (401, 403, 429):
            raise AccessRestrictedError(f"외부 사이트 접근 제한: HTTP {response.status_code}")
        if response.headers.get("Retry-After") is not None:
            raise AccessRestrictedError("외부 사이트의 대기 요청으로 수집 중지")
        if response.status_code >= 500:
            raise TransientHttpError(f"외부 사이트 서버 오류: HTTP {response.status_code}")
        if not 200 <= response.status_code < 300:
            raise UnexpectedResponseError(f"예상하지 못한 HTTP 상태: {response.status_code}")
        if "json" not in response.headers.get("Content-Type", "").lower():
            content = response.text.lower()
            if any(
                marker in content
                for marker in ("cf-chl-", "verify you are human", "<title>access denied")
            ):
                raise AccessRestrictedError("외부 사이트 접근 확인 화면으로 수집 중지")
        return response
