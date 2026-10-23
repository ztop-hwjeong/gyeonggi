import os
from contextlib import contextmanager
from unittest.mock import Mock
from uuid import uuid4

import psycopg
import pytest
from prefect.client.schemas.objects import State, StateType
from psycopg.rows import DictRow, dict_row
from psycopg.types.json import Jsonb

from control.dispatch import reconcile, schedule_due, submit_one
from control.models import ControlSettings
from control.repository import ControlRepository


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
            "interval_minutes": 15,
        }
        conn.execute(
            "INSERT INTO ops.collection_rules(id,version,definition) VALUES (%s,1,%s)",
            (rule_id, Jsonb(definition)),
        )
        conn.execute(
            "INSERT INTO ops.collection_rule_versions(rule_id,version,definition) VALUES (%s,1,%s)",
            (rule_id, Jsonb(definition)),
        )
        assert schedule_due(repository, 20) == 1
        conn.execute("UPDATE ops.collection_rules SET next_run_at=now() WHERE id=%s", (rule_id,))
        assert schedule_due(repository, 20) == 0
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
        conn.rollback()
