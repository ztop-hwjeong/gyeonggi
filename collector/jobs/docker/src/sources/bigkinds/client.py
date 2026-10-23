from collector_http.client import ChromiumHttpClient

from sources.bigkinds.config import BigKindsSettings
from sources.bigkinds.models import ListCollectionRequest


def search_payload(request: ListCollectionRequest, page_number: int) -> dict:
    if page_number < 1:
        raise ValueError("페이지 번호는 1 이상 필요")
    return {
        "indexName": "news",
        "searchKey": request.search_key,
        "searchKeys": [{}],
        "byLine": "",
        "searchFilterType": "1",
        "searchScopeType": "1",
        "searchSortType": "date",
        "sortMethod": "date",
        "mainTodayPersonYn": "",
        "startDate": request.start_date.isoformat(),
        "endDate": request.end_date.isoformat(),
        "newsIds": [],
        "categoryCodes": [],
        "providerCodes": list(request.provider_codes),
        "incidentCodes": [],
        "networkNodeType": "",
        "topicOrigin": "",
        "dateCodes": [],
        "editorialIs": False,
        "startNo": page_number,
        "resultNumber": request.page_size,
        "isTmUsable": False,
        "isNotTmUsable": False,
    }


class BigKindsClient:
    def __init__(self, settings: BigKindsSettings, http: ChromiumHttpClient) -> None:
        self._base_url = str(settings.base_url).rstrip("/")
        self._http = http

    def warmup(self) -> None:
        self._http.request("GET", self._base_url + "/v2/news/search.do")

    def search(self, request: ListCollectionRequest, page_number: int) -> bytes:
        response = self._http.request(
            "POST",
            self._base_url + "/api/news/search.do",
            json=search_payload(request, page_number),
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Accept-Language": "ko,en-US;q=0.9,en;q=0.8",
                "Origin": self._base_url,
                "Referer": self._base_url + "/v2/news/search.do",
                "X-Requested-With": "XMLHttpRequest",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
            },
        )
        return response.content
