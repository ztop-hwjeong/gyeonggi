from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from collector_http.client import ChromiumHttpClient
from curl_cffi.requests import Response

from sources.naver.config import NaverCredentials, NaverSettings
from sources.naver.models import SearchPage, SearchRequest


class NaverApiError(RuntimeError):
    def __init__(self, status: int, code: str | None, retry_after: str | None = None) -> None:
        self.code = code
        self.status = status
        self.retry_after_seconds: float | None = None
        if retry_after is not None:
            try:
                self.retry_after_seconds = max(0, float(retry_after))
            except ValueError:
                try:
                    value = parsedate_to_datetime(retry_after)
                    self.retry_after_seconds = max(0, (value - datetime.now(UTC)).total_seconds())
                except (ValueError, TypeError):
                    pass
        super().__init__(f"네이버 API HTTP {status}" + (f" ({code})" if code else ""))


class NaverClient:
    def __init__(
        self, http: ChromiumHttpClient, settings: NaverSettings, credentials: NaverCredentials
    ) -> None:
        self.http = http
        self.base_url = str(settings.base_url).rstrip("/")
        self.credentials = credentials

    def fetch(self, request: SearchRequest, start: int) -> Response:
        return self.http.request_raw(
            "GET",
            self.base_url + f"/search/v1/{request.channel}",
            params={
                "query": request.query,
                "display": request.page_size,
                "start": start,
                "sort": "date",
                "format": "json",
            },
            headers={
                "X-NCP-APIGW-API-KEY-ID": self.credentials.client_id.get_secret_value(),
                "X-NCP-APIGW-API-KEY": self.credentials.client_secret.get_secret_value(),
            },
        )


def parse_response(response: Response, expected_start: int) -> SearchPage:
    if response.status_code != 200 or response.headers.get("Retry-After") is not None:
        code = None
        try:
            data = response.json()
            value = data.get("errorCode") or data.get("error", {}).get("errorCode")
            if isinstance(value, str) and len(value) <= 40:
                code = value
        except (ValueError, AttributeError, TypeError):
            pass
        raise NaverApiError(response.status_code, code, response.headers.get("Retry-After"))
    page = SearchPage.model_validate_json(response.content)
    if page.start != expected_start or page.display != len(page.items):
        raise ValueError("네이버 응답 시작 위치·항목 수 불일치")
    return page
