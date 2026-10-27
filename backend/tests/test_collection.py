from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from dishka import Provider, Scope, make_async_container, provide
from fastapi.testclient import TestClient
from pydantic import ValidationError

from domain.collection.errors import CollectionConflictError, CollectionUnavailableError
from domain.collection.models import PreviewCreate, RuleDefinition, RunCreate
from domain.collection.repository import CollectionRepository
from main import create_app


@pytest.fixture
def definition():
    return {"name": "교육 정책", "terms": ["교권보호", "폰프리 스쿨"], "sources": ["bigkinds"]}


@pytest.fixture
def setup_collection(definition):
    repository = AsyncMock(spec=CollectionRepository)

    class TestProvider(Provider):
        @provide(scope=Scope.REQUEST)
        def repo(self) -> CollectionRepository:
            return repository

    now = datetime.now(UTC)
    rule_id = uuid4()
    repository.save_rule.return_value = {
        "id": rule_id,
        "version": 1,
        "definition": definition,
        "created_at": now,
        "updated_at": now,
    }
    with TestClient(create_app(make_async_container(TestProvider()))) as client:
        yield client, repository, rule_id


def test_create_and_update_rule_pass_expected_version(setup_collection, definition):
    client, repository, rule_id = setup_collection
    created = client.post("/keyword-rules", json=definition)
    assert created.status_code == 201
    assert created.json()["definition"]["enabled"] is False
    updated = client.put(f"/keyword-rules/{rule_id}", json={**definition, "version": 1})
    assert updated.status_code == 200
    assert repository.save_rule.await_args.args[0].version == 1
    repository.save_rule.side_effect = CollectionConflictError("버전 충돌")
    assert (
        client.put(f"/keyword-rules/{rule_id}", json={**definition, "version": 1}).status_code
        == 409
    )


def test_retired_collection_source_cannot_be_registered(setup_collection, definition):
    client, repository, _ = setup_collection
    response = client.post("/keyword-rules", json={**definition, "sources": ["naver_cafearticle"]})
    assert response.status_code == 422
    repository.save_rule.assert_not_awaited()


def test_run_requires_idempotency_key_and_supported_period(setup_collection):
    client, repository, rule_id = setup_collection
    body = {
        "rule_id": str(rule_id),
        "version": 1,
        "source": "bigkinds",
        "mode": "backfill",
        "start_date": "2026-06-01",
        "end_date": "2026-10-23",
    }
    assert client.post("/collection-runs", json=body).status_code == 422
    key = str(uuid4())
    unsupported = client.post(
        "/collection-runs", json={**body, "source": "naver_blog"}, headers={"Idempotency-Key": key}
    )
    assert unsupported.status_code == 422
    repository.enqueue.assert_not_awaited()


def test_preview_enqueues_draft_without_saving_rule(setup_collection, definition):
    client, repository, _ = setup_collection
    now = datetime.now(UTC)
    key = uuid4()
    repository.enqueue.return_value = {
        "id": key,
        "rule_id": None,
        "rule_version": None,
        "source": "bigkinds",
        "mode": "preview",
        "definition": definition,
        "start_date": "2026-06-01",
        "end_date": "2026-10-23",
        "status": "queued",
        "flow_run_id": None,
        "summary": {},
        "error": None,
        "created_at": now,
        "updated_at": now,
    }
    response = client.post(
        "/collection-previews",
        headers={"Idempotency-Key": str(key)},
        json={
            "definition": definition,
            "source": "bigkinds",
            "start_date": "2026-06-01",
            "end_date": "2026-10-23",
        },
    )
    assert response.status_code == 202
    assert repository.enqueue.await_args.args[0] == key
    assert isinstance(repository.enqueue.await_args.args[1], PreviewCreate)
    repository.save_rule.assert_not_awaited()


def test_unavailable_storage_is_not_an_empty_list(setup_collection):
    client, repository, _ = setup_collection
    repository.rules.side_effect = CollectionUnavailableError("저장소 연결 실패")
    assert client.get("/keyword-rules").status_code == 503


def test_request_filters_are_validated_and_passed_together(setup_collection):
    client, repository, rule_id = setup_collection
    repository.requests.return_value = {"items": [], "total": 0}
    response = client.get(
        "/collection-runs",
        params={
            "rule_id": str(rule_id),
            "status": "attention",
            "source": "bigkinds",
            "mode": "backfill",
            "offset": 20,
        },
    )
    assert response.status_code == 200
    query = repository.requests.await_args.args[0]
    assert (query.rule_id, query.status, query.source, query.mode, query.offset) == (
        rule_id,
        "attention",
        "bigkinds",
        "backfill",
        20,
    )
    assert client.get("/collection-runs?status=typo").status_code == 422
    repository.rules.return_value = {"items": [], "total": 0}
    assert client.get("/keyword-rules?q=교육&enabled=false").status_code == 200
    assert repository.rules.await_args.args[0].enabled is False


def test_terms_preserve_phrases_and_deduplicate(definition):
    rule = RuleDefinition.model_validate({**definition, "terms": ["  경기  교육 ", "경기 교육"]})
    assert rule.terms == ("경기 교육",)
    with pytest.raises(ValidationError):
        RuleDefinition.model_validate({**definition, "terms": ['"경기" | "교육"']})


def test_rule_interval_is_rejected(definition):
    with pytest.raises(ValidationError):
        RuleDefinition.model_validate({**definition, "interval_minutes": 15})


def test_period_rejects_reverse_dates_and_allows_long_history():
    base = {"rule_id": uuid4(), "version": 1, "source": "bigkinds", "mode": "backfill"}
    with pytest.raises(ValidationError):
        RunCreate.model_validate({**base, "start_date": "2026-10-23", "end_date": "2026-06-01"})
    request = RunCreate.model_validate(
        {**base, "start_date": "2024-01-01", "end_date": "2026-10-23"}
    )
    assert request.start_date.year == 2024
