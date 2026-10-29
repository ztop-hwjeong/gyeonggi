import os
from contextlib import contextmanager
from unittest.mock import Mock
from uuid import uuid4

import psycopg
import pytest
from prefect.client.schemas.objects import State, StateType
from psycopg.rows import DictRow, dict_row
from psycopg.types.json import Jsonb

from control.dispatch import enqueue_enabled, reconcile, submit_one
from control.models import ControlSettings
from control.repository import ControlRepository


def test_dispatch_recovers_finished_request_before_enqueuing(monkeypatch):
    from flows import dispatch

    active = ["finished-prefect-run"]
    queued = []

    def enqueue(repository):
        if active:
            return 0
        queued.append("next-request")
        return 1

    def submit(repository, client, settings):
        return bool(queued and queued.pop())

    @contextmanager
    def client_scope(**kwargs):
        yield Mock()

    monkeypatch.setattr(dispatch, "control_repository", Mock(return_value=Mock()))
    monkeypatch.setattr(dispatch, "get_client", client_scope)
    monkeypatch.setattr(dispatch, "get_run_logger", Mock(return_value=Mock()))
    monkeypatch.setattr(dispatch, "reconcile", lambda *args: active.clear())
    monkeypatch.setattr(dispatch, "enqueue_enabled", enqueue)
    monkeypatch.setattr(dispatch, "submit_one", submit)

    assert dispatch.dispatch_collections.fn() == {"scheduled": 1, "submitted": 1}
    assert not queued


@pytest.mark.skipif(not os.environ.get("CONTROL_TEST_DATABASE_DSN"), reason="전용 검증 DB 필요")
def test_dispatch_recovery_preview_isolation_and_final_state_preservation(monkeypatch):
    with psycopg.Connection[DictRow].connect(
        os.environ["CONTROL_TEST_DATABASE_DSN"], row_factory=dict_row
    ) as conn:

        @contextmanager
        def connect():
            yield conn

        repository = ControlRepository(Mock(), Mock())
        monkeypatch.setattr(repository, "connect", connect)
        rule_id, run_id = uuid4(), uuid4()
        definition = {
            "name": "검증",
            "terms": ["교육"],
            "sources": ["bigkinds"],
            "enabled": True,
        }
        conn.execute(
            "INSERT INTO ops.collection_rules(id,version,definition) VALUES (%s,1,%s)",
            (rule_id, Jsonb(definition)),
        )
        conn.execute(
            "INSERT INTO ops.collection_rule_versions(rule_id,version,definition) VALUES (%s,1,%s)",
            (rule_id, Jsonb(definition)),
        )
        assert enqueue_enabled(repository) == 1
        assert enqueue_enabled(repository) == 0
        request_id = conn.execute("SELECT id FROM ops.collection_requests").fetchall()[0]["id"]
        client = Mock()
        client.create_flow_run_from_deployment.side_effect = [TimeoutError(), Mock(id=run_id)]
        with pytest.raises(TimeoutError):
            submit_one(repository, client, ControlSettings())
        assert (
            conn.execute("SELECT status FROM ops.collection_requests").fetchall()[0]["status"]
            == "queued"
        )
        assert submit_one(repository, client, ControlSettings())
        keys = [
            call.kwargs["idempotency_key"]
            for call in client.create_flow_run_from_deployment.call_args_list
        ]
        assert len(set(keys)) == 1
        request = repository.start(request_id, run_id)
        assert request is not None
        assert repository.start(request_id, run_id) is None
        item = {"source_id": "a", "title": "교육 정책", "summary": "요약"}
        repository.save_items(request.model_copy(update={"mode": "preview"}), [item])
        assert (
            conn.execute("SELECT count(*) AS count FROM dw.news_items").fetchall()[0]["count"] == 0
        )
        repository.save_items(request, [item])
        assert (
            conn.execute("SELECT count(*) AS count FROM dw.news_items").fetchall()[0]["count"] == 1
        )
        repository.progress(request_id, {"retrieved_count": 1})
        repository.finish(request_id, "completed", {})
        client.read_flow_run.return_value = Mock(id=run_id, state=State(type=StateType.COMPLETED))
        reconcile(repository, client, 20)
        row = conn.execute("SELECT status,summary FROM ops.collection_requests").fetchall()[0]
        assert row["status"] == "completed"
        assert row["summary"]["retrieved_count"] == 1
        conn.execute(
            "INSERT INTO ops.collection_requests "
            "(id,rule_id,rule_version,source,mode,definition,start_date,end_date) "
            "SELECT %s,rule_id,rule_version,source,'backfill',definition,start_date,end_date "
            "FROM ops.collection_requests WHERE id=%s",
            (uuid4(), request_id),
        )
        client.create_flow_run_from_deployment.side_effect = None
        client.create_flow_run_from_deployment.return_value = Mock(id=uuid4())
        assert submit_one(repository, client, ControlSettings())
        destinations = [call.args[0] for call in client.read_deployment_by_name.call_args_list]
        assert destinations[0] != destinations[-1]
        conn.rollback()


@pytest.mark.skipif(not os.environ.get("CONTROL_TEST_DATABASE_DSN"), reason="전용 검증 DB 필요")
def test_all_enabled_rules_enqueue_beyond_submit_batch(monkeypatch):
    with psycopg.Connection[DictRow].connect(
        os.environ["CONTROL_TEST_DATABASE_DSN"], row_factory=dict_row
    ) as conn:

        @contextmanager
        def connect():
            yield conn

        repository = ControlRepository(Mock(), Mock())
        monkeypatch.setattr(repository, "connect", connect)
        rule_ids = [uuid4() for _ in range(ControlSettings().dispatch_batch_size + 3)]
        try:
            for rule_id in rule_ids:
                definition = {
                    "name": f"검증 {rule_id}",
                    "terms": ["교육"],
                    "sources": ["bigkinds"],
                    "enabled": True,
                }
                conn.execute(
                    "INSERT INTO ops.collection_rules(id,version,definition) VALUES (%s,1,%s)",
                    (rule_id, Jsonb(definition)),
                )
                conn.execute(
                    "INSERT INTO ops.collection_rule_versions(rule_id,version,definition) "
                    "VALUES (%s,1,%s)",
                    (rule_id, Jsonb(definition)),
                )
            assert enqueue_enabled(repository) == len(rule_ids)
            assert enqueue_enabled(repository) == 0
            row = conn.execute(
                "SELECT count(*) AS count FROM ops.collection_requests "
                "WHERE rule_id = ANY(%s) AND status='queued'",
                (rule_ids,),
            ).fetchone()
            assert row is not None and row["count"] == len(rule_ids)
        finally:
            conn.rollback()
