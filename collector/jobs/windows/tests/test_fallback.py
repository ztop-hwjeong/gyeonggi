from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest

from articles.models import ArticleSeed, DetailAttempt, FetchSnapshot
from articles.pipeline import browser_allowed
from flows import details


@pytest.mark.parametrize(
    "stages,statuses,expected",
    [
        (["curl_cffi"], ["accepted"], "curl_cffi"),
        (["curl_cffi", "browser_fetch"], ["failed", "accepted"], "browser_fetch"),
        (
            ["curl_cffi", "browser_fetch", "bigkinds_api"],
            ["failed", "rejected", "accepted"],
            "bigkinds_api",
        ),
        (["curl_cffi", "browser_fetch", "bigkinds_api"], ["failed", "failed", "failed"], None),
    ],
)
def test_stage_order_and_early_success(
    monkeypatch: pytest.MonkeyPatch,
    seed: ArticleSeed,
    repository: Mock,
    stages: list,
    statuses: list,
    expected: str | None,
) -> None:
    for name, value in {
        "DATABASE_HOST": "test.invalid",
        "DATABASE_PORT": "5432",
        "DATABASE_NAME": "test",
        "DATABASE_USER": "test",
        "DATABASE_PASSWORD_BLOCK": "test",
        "BROWSER_CDP_URL": "http://127.0.0.1:9222",
        "DETAIL_BIGKINDS_RATE_LIMIT_NAME": "test",
        "OBJECT_STORAGE_ENDPOINT_URL": "http://127.0.0.1:9000",
        "OBJECT_STORAGE_BUCKET": "test",
        "OBJECT_STORAGE_REGION": "us-east-1",
        "OBJECT_STORAGE_CREDENTIALS_BLOCK": "objects-test",
    }.items():
        monkeypatch.setenv(name, value)
    collector = Mock()
    collector.attempt.side_effect = [
        DetailAttempt(stage=stage, status=status, reason="test")
        for stage, status in zip(stages, statuses, strict=True)
    ]
    monkeypatch.setattr(details, "ArticleDetailCollector", Mock(return_value=collector))
    monkeypatch.setattr(details, "DetailRepository", Mock(return_value=repository))
    monkeypatch.setattr(details, "RawObjectStore", MagicMock())
    monkeypatch.setattr(
        details.Secret,
        "load",
        Mock(return_value=Mock(get=lambda: {"access_key": "test", "secret_key": "test"})),
    )
    monkeypatch.setattr(
        details.FlowRunContext, "get", lambda: SimpleNamespace(flow_run=SimpleNamespace(id=uuid4()))
    )
    monkeypatch.setattr(details, "get_run_logger", Mock())
    monkeypatch.setattr(details, "collect_stage", details.collect_stage.fn)
    monkeypatch.setattr(details, "finish_article", details.finish_article.fn)
    result = details.collect_article_details.fn([seed])
    assert [call.args[0] for call in collector.attempt.call_args_list] == stages
    stored = repository.save_detail.call_args.args[1]
    assert stored.selected_stage == expected
    assert result.collected_count == (1 if expected is not None else 0)
    assert result.status == ("completed" if expected is not None else "partial")


@pytest.mark.parametrize("status,retry_after", [(401, None), (429, None), (503, "120")])
def test_publisher_wait_or_authentication_prevents_browser_repetition(
    status: int, retry_after: str | None
) -> None:
    response = FetchSnapshot(
        response_id=uuid4(),
        url="https://example.org",
        status_code=status,
        content_type="text/html",
        sha256="a" * 64,
        received_at=datetime.now(UTC),
        retry_after=retry_after,
    )
    assert not browser_allowed(
        DetailAttempt(stage="curl_cffi", status="failed", reason="test", snapshots=[response])
    )


def test_403_allows_authorized_browser_stage() -> None:
    response = FetchSnapshot(
        response_id=uuid4(),
        url="https://example.org",
        status_code=403,
        content_type="text/html",
        sha256="a" * 64,
        received_at=datetime.now(UTC),
    )
    assert browser_allowed(
        DetailAttempt(stage="curl_cffi", status="failed", reason="test", snapshots=[response])
    )
