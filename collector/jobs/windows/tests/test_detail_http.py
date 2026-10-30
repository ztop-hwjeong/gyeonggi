import json
from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest
from collector_http.config import HttpSettings

from articles.http import extract_bigkinds_detail, fetch_bigkinds
from articles.models import ArticleSeed, FetchSnapshot
from articles.requests import RequestStoppedError
from config import DetailSettings, ExtractionSettings


@pytest.mark.parametrize("host, verified", [("www.ajunews.com", True), ("other.example", False)])
def test_official_photo_caption_uses_registered_domain_validation(seed, host, verified):
    title = "[포토] 산업 데이터 분과 출범식 참석"
    body = (
        "김정관 산업통상부 장관이 서울 행사장에서 데이터 분과 출범식에 참석해 인사말을 하고 있다. "
        "이번 행사에는 기업 관계자들도 참석했다."
    )
    seeded = seed.model_copy(
        update={
            "title": title,
            "summary": "[사진=한준구 기자 example@ajunews.com] " + body,
            "original_url": f"https://{host}/view/20261029140709543",
        }
    )
    result = extract_bigkinds_detail(
        seeded,
        {"NEWS_ID": seeded.source_id, "TITLE": title, "CONTENT": body},
        ExtractionSettings(),
    )

    assert result.evidence.verified is verified
    assert result.text == body


@pytest.fixture
def transport(monkeypatch: pytest.MonkeyPatch) -> tuple:
    http = Mock()
    client = MagicMock()
    client.__enter__.return_value = http
    monkeypatch.setattr("articles.http.ChromiumHttpClient", Mock(return_value=client))
    store = Mock()

    def save(stage, url, status, content_type, body, retry_after):
        return FetchSnapshot(
            response_id=uuid4(),
            url=url,
            status_code=status,
            content_type=content_type,
            sha256=sha256(body).hexdigest(),
            retry_after=retry_after,
            received_at=datetime.now(UTC),
        )

    store.save_response.side_effect = save
    return http, store


def response(status: int, body: bytes, **headers: str) -> SimpleNamespace:
    return SimpleNamespace(status_code=status, content=body, headers=headers)


def test_bigkinds_initializes_session_and_verifies_detail(
    transport: tuple, seed: ArticleSeed, article_text: str
) -> None:
    http, store = transport
    http.request_raw.side_effect = [
        response(200, b"<html>search</html>"),
        response(
            200,
            json.dumps(
                {
                    "detail": {
                        "NEWS_ID": seed.source_id,
                        "TITLE": seed.title,
                        "CONTENT": article_text,
                    }
                }
            ).encode(),
        ),
    ]
    snapshots = []
    result = fetch_bigkinds(
        seed,
        store,
        DetailSettings(bigkinds_rate_limit_name="test"),
        HttpSettings(),
        Mock(),
        ExtractionSettings(),
        snapshots,
    )
    assert result.evidence.verified
    assert result.method == "bigkinds_api"
    assert len(snapshots) == 2
    assert http.request_raw.call_args_list[0].args[1].endswith("/v2/news/search.do")


@pytest.mark.parametrize("status,retry_after", [(403, None), (429, None), (200, "120")])
def test_failed_session_does_not_request_detail(
    transport: tuple, seed: ArticleSeed, status: int, retry_after: str | None
) -> None:
    http, store = transport
    http.request_raw.return_value = response(
        status, b"restricted", **({"Retry-After": retry_after} if retry_after else {})
    )
    snapshots = []
    with pytest.raises(RequestStoppedError, match="세션 초기화"):
        fetch_bigkinds(
            seed,
            store,
            DetailSettings(bigkinds_rate_limit_name="test"),
            HttpSettings(),
            Mock(),
            ExtractionSettings(),
            snapshots,
        )
    assert http.request_raw.call_count == 1
    assert len(snapshots) == 1


def test_other_article_id_is_rejected(transport: tuple, seed: ArticleSeed) -> None:
    http, store = transport
    http.request_raw.side_effect = [
        response(200, b"search"),
        response(200, b'{"detail":{"NEWS_ID":"other-article"}}'),
    ]
    with pytest.raises(RequestStoppedError, match="ID 불일치"):
        fetch_bigkinds(
            seed,
            store,
            DetailSettings(bigkinds_rate_limit_name="test"),
            HttpSettings(),
            Mock(),
            ExtractionSettings(),
            [],
        )


@pytest.mark.parametrize("change", ["none", "short_body", "wrong_title"])
def test_title_only_listing_requires_verified_detail_identity_and_full_body(
    transport, seed, article_text, change
):
    http, store = transport
    seed = seed.model_copy(update={"summary": seed.title})
    http.request_raw.side_effect = [
        response(200, b"search"),
        response(
            200,
            json.dumps(
                {
                    "detail": {
                        "NEWS_ID": seed.source_id,
                        "TITLE": "전혀 다른 국제 금융 기사"
                        if change == "wrong_title"
                        else seed.title,
                        "CONTENT": seed.title if change == "short_body" else article_text,
                    }
                }
            ).encode(),
        ),
    ]
    result = fetch_bigkinds(
        seed,
        store,
        DetailSettings(bigkinds_rate_limit_name="test"),
        HttpSettings(),
        Mock(),
        ExtractionSettings(),
        [],
    )
    assert result.evidence.verified is (change == "none")
    if change == "none":
        assert "기사 ID·제목 일치" in result.evidence.reason


@pytest.mark.parametrize(
    ("title", "summary", "body", "verified"),
    [
        (
            "북한 황해도 개풍군",
            (
                "28일 경기도 김포시 애기봉 전망대에서 바라본 북한 황해도 개풍군 "
                "접경지역에서 북한 주민들이 포착되고 있다."
            ),
            (
                "28일 경기도 김포시 애기봉 전망대에서 바라본 북한 황해도 개풍군 "
                "접경지역에서 북한 주민들이 포착되고 있다.\n진실은 노컷, 거짓은 칼컷"
            ),
            True,
        ),
        (
            "북한 황해도 개풍군",
            "북한 황해도 개풍군",
            "북한 황해도 개풍군\n진실은 노컷, 거짓은 칼컷",
            False,
        ),
        ("다른 제목", "단문 원문 문장입니다.", "단문 원문 문장입니다.", False),
        (
            "북한 황해도 개풍군",
            "첫 번째 문장입니다. 두 번째 문장입니다.",
            "첫 번째 문장입니다.",
            False,
        ),
        ("북한 황해도 개풍군", "단문 원문 문장입니다.", "", False),
        ("북한 황해도 개풍군", "짧은 목록 요약", "짧은 목록 요약 뒤 문장", False),
    ],
)
def test_bigkinds_exact_short_body_requires_full_listing_summary(
    transport, seed, title, summary, body, verified
):
    http, store = transport
    seed = seed.model_copy(update={"title": "북한 황해도 개풍군", "summary": summary})
    http.request_raw.side_effect = [
        response(200, b"search"),
        response(
            200,
            json.dumps(
                {
                    "detail": {
                        "NEWS_ID": seed.source_id,
                        "TITLE": title,
                        "CONTENT": body,
                    }
                }
            ).encode(),
        ),
    ]

    result = fetch_bigkinds(
        seed,
        store,
        DetailSettings(bigkinds_rate_limit_name="test"),
        HttpSettings(),
        Mock(),
        ExtractionSettings(),
        [],
    )

    assert result.evidence.verified is verified
    if verified:
        assert result.evidence.reason == "빅카인즈 단문 원문·목록 요약 일치"


@pytest.mark.parametrize(
    ("title", "body", "verified"),
    [
        (
            "공식 상세 기사 제목",
            "공식 상세 기사 제목\n" + "실제 기사 본문입니다. " * 40,
            True,
        ),
        (
            "공식 상세 기사 제목",
            "공식 상세 기사 제목\n" * 40,
            False,
        ),
        (
            "공식 상세 기사 제목",
            "공식 상세 기사 제목\n여러분의 제보가 CBS노컷뉴스의 시작입니다. " * 20,
            False,
        ),
        (
            "공식 상세 기사 제목",
            "공식 상세 기사 제목\n진실은 노컷, 거짓은 칼컷. " * 30,
            False,
        ),
        (
            "다른 공식 기사 제목",
            "공식 상세 기사 제목\n" + "실제 기사 본문입니다. " * 40,
            False,
        ),
    ],
)
def test_bigkinds_official_detail_accepts_long_body_despite_listing_summary_mismatch(
    transport, seed, title, body, verified
):
    http, store = transport
    seed = seed.model_copy(
        update={
            "title": "공식 상세 기사 제목",
            "summary": "목록에서 갱신된 전혀 다른 요약 문장입니다. " * 8,
        }
    )
    http.request_raw.side_effect = [
        response(200, b"search"),
        response(
            200,
            json.dumps(
                {
                    "detail": {
                        "NEWS_ID": seed.source_id,
                        "TITLE": title,
                        "CONTENT": body,
                    }
                }
            ).encode(),
        ),
    ]

    result = fetch_bigkinds(
        seed,
        store,
        DetailSettings(bigkinds_rate_limit_name="test"),
        HttpSettings(),
        Mock(),
        ExtractionSettings(),
        [],
    )

    assert result.evidence.verified is verified
    if verified:
        assert result.evidence.reason == "빅카인즈 공식 기사 ID·제목 일치 및 본문 확인"
