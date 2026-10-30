import os
from contextlib import contextmanager
from datetime import date
from unittest.mock import Mock
from uuid import uuid4

import psycopg
import pytest
from prefect.client.schemas.objects import State, StateType
from psycopg.rows import DictRow, dict_row
from psycopg.types.json import Jsonb
from sqlalchemy import create_engine, delete, insert, select, update

from control.dispatch import enqueue_enabled, reconcile, submit_one
from control.models import CollectionCancelled, ControlSettings
from control.repository import ControlRepository
from control.tables import (
    analysis_targets,
    collection_request_items,
    collection_requests,
    collection_rule_targets,
    collection_rule_versions,
    collection_rules,
)


def mapping_engine():
    return create_engine(
        os.environ["CONTROL_TEST_DATABASE_DSN"].replace("postgresql://", "postgresql+psycopg://", 1)
    )


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

    @contextmanager
    def control_scope():
        yield Mock()

    monkeypatch.setattr(dispatch, "control_scope", control_scope)
    monkeypatch.setattr(dispatch, "get_client", client_scope)
    monkeypatch.setattr(dispatch, "get_run_logger", Mock(return_value=Mock()))
    monkeypatch.setattr(dispatch, "reconcile", lambda *args: active.clear())
    monkeypatch.setattr(dispatch, "enqueue_enabled", enqueue)
    monkeypatch.setattr(dispatch, "submit_one", submit)

    assert dispatch.dispatch_collections.fn() == {"scheduled": 1, "submitted": 1}
    assert not queued


@pytest.mark.skipif(not os.environ.get("CONTROL_TEST_DATABASE_DSN"), reason="전용 검증 DB 필요")
def test_dispatch_recovery_preview_isolation_and_final_state_preservation(monkeypatch, request):
    engine = mapping_engine()
    request.addfinalizer(engine.dispose)
    rule_id = uuid4()

    def cleanup() -> None:
        with engine.begin() as connection:
            request_ids = select(collection_requests.c.id).where(
                collection_requests.c.rule_id == rule_id
            )
            connection.execute(
                delete(collection_request_items).where(
                    collection_request_items.c.request_id.in_(request_ids)
                )
            )
            connection.execute(
                delete(collection_requests).where(collection_requests.c.rule_id == rule_id)
            )
            connection.execute(
                delete(collection_rule_versions).where(
                    collection_rule_versions.c.rule_id == rule_id
                )
            )
            connection.execute(delete(collection_rules).where(collection_rules.c.id == rule_id))

    request.addfinalizer(cleanup)
    with psycopg.Connection[DictRow].connect(
        os.environ["CONTROL_TEST_DATABASE_DSN"], row_factory=dict_row
    ) as conn:

        @contextmanager
        def connect():
            yield conn

        repository = ControlRepository(Mock(), Mock(), engine)
        monkeypatch.setattr(repository, "connect", connect)
        run_id = uuid4()
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
        conn.commit()
        conn.execute(
            "INSERT INTO ops.collection_rule_versions(rule_id,version,definition) VALUES (%s,1,%s)",
            (rule_id, Jsonb(definition)),
        )
        conn.commit()
        assert enqueue_enabled(repository) == 1
        assert enqueue_enabled(repository) == 0
        queued_request = conn.execute(
            "SELECT id FROM ops.collection_requests WHERE rule_id=%s AND source='bigkinds' "
            "AND mode='incremental'",
            (rule_id,),
        ).fetchone()
        assert queued_request is not None
        request_id = queued_request["id"]
        client = Mock()
        client.create_flow_run_from_deployment.side_effect = [TimeoutError(), Mock(id=run_id)]
        with pytest.raises(TimeoutError):
            submit_one(repository, client, ControlSettings())
        assert (
            conn.execute("SELECT status FROM ops.collection_requests").fetchall()[0]["status"]
            == "queued"
        )
        assert submit_one(repository, client, ControlSettings())
        conn.commit()
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
        preview_count = conn.execute(
            "SELECT count(*) AS count FROM dw.news_items WHERE source='bigkinds' AND source_id='a'"
        ).fetchone()
        assert preview_count is not None and preview_count["count"] == 0
        repository.save_items(request, [item])
        saved_count = conn.execute(
            "SELECT count(*) AS count FROM dw.news_items WHERE source='bigkinds' AND source_id='a'"
        ).fetchone()
        assert saved_count is not None and saved_count["count"] == 1
        repository.progress(request_id, {"retrieved_count": 1})
        repository.finish(request_id, "completed", {})
        client.read_flow_run.return_value = Mock(id=run_id, state=State(type=StateType.COMPLETED))
        reconcile(repository, client, 20)
        row = conn.execute(
            "SELECT status,summary FROM ops.collection_requests WHERE id=%s", (request_id,)
        ).fetchone()
        assert row is not None
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
        conn.execute(
            "DELETE FROM st.collection_request_items WHERE request_id IN "
            "(SELECT id FROM ops.collection_requests WHERE rule_id=%s)",
            (rule_id,),
        )
        conn.execute("DELETE FROM ops.collection_requests WHERE rule_id=%s", (rule_id,))
        conn.execute("DELETE FROM dw.news_items WHERE source='bigkinds' AND source_id='a'")
        conn.execute("DELETE FROM ops.collection_rule_versions WHERE rule_id=%s", (rule_id,))
        conn.execute("DELETE FROM ops.collection_rules WHERE id=%s", (rule_id,))
        conn.commit()


@pytest.mark.skipif(not os.environ.get("CONTROL_TEST_DATABASE_DSN"), reason="전용 검증 DB 필요")
def test_all_enabled_rules_enqueue_beyond_submit_batch(monkeypatch, request):
    engine = mapping_engine()
    request.addfinalizer(engine.dispose)
    with psycopg.Connection[DictRow].connect(
        os.environ["CONTROL_TEST_DATABASE_DSN"], row_factory=dict_row
    ) as conn:

        @contextmanager
        def connect():
            yield conn

        repository = ControlRepository(Mock(), Mock(), engine)
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
            conn.commit()
            assert enqueue_enabled(repository) == len(rule_ids)
            assert enqueue_enabled(repository) == 0
            row = conn.execute(
                "SELECT count(*) AS count FROM ops.collection_requests "
                "WHERE rule_id = ANY(%s) AND status='queued'",
                (rule_ids,),
            ).fetchone()
            assert row is not None and row["count"] == len(rule_ids)
        finally:
            conn.execute(
                "DELETE FROM st.collection_request_items WHERE request_id IN "
                "(SELECT id FROM ops.collection_requests WHERE rule_id = ANY(%s))",
                (rule_ids,),
            )
            conn.execute("DELETE FROM ops.collection_requests WHERE rule_id = ANY(%s)", (rule_ids,))
            conn.execute(
                "DELETE FROM ops.collection_rule_versions WHERE rule_id = ANY(%s)", (rule_ids,)
            )
            conn.execute("DELETE FROM ops.collection_rules WHERE id = ANY(%s)", (rule_ids,))
            conn.commit()


@pytest.mark.skipif(not os.environ.get("CONTROL_TEST_DATABASE_DSN"), reason="전용 검증 DB 필요")
def test_target_collection_flag_controls_scheduling_and_running_request(request) -> None:
    engine = mapping_engine()
    request.addfinalizer(engine.dispose)
    disabled_rule, shared_rule, unmapped_rule = uuid4(), uuid4(), uuid4()
    disabled_target, enabled_target = uuid4(), uuid4()
    request_id, flow_run_id = uuid4(), uuid4()
    definition = {"name": "검증", "terms": ["교육"], "sources": ["bigkinds"], "enabled": True}
    repository = ControlRepository(Mock(), Mock(), engine)
    try:
        with engine.begin() as connection:
            connection.execute(
                delete(collection_request_items).where(
                    collection_request_items.c.request_id == request_id
                )
            )
            connection.execute(
                insert(collection_rules),
                [
                    {"id": disabled_rule, "version": 1, "definition": definition},
                    {"id": shared_rule, "version": 1, "definition": definition},
                    {"id": unmapped_rule, "version": 1, "definition": definition},
                ],
            )
            connection.execute(
                insert(collection_rule_versions),
                [
                    {"rule_id": disabled_rule, "version": 1, "definition": definition},
                    {"rule_id": shared_rule, "version": 1, "definition": definition},
                    {"rule_id": unmapped_rule, "version": 1, "definition": definition},
                ],
            )
            connection.execute(
                insert(analysis_targets),
                [
                    {
                        "id": disabled_target,
                        "kind": "current_issue",
                        "name": "중단 현안",
                        "collection_enabled": False,
                    },
                    {
                        "id": enabled_target,
                        "kind": "regular",
                        "name": "계속 현안",
                        "collection_enabled": True,
                    },
                ],
            )
            connection.execute(
                insert(collection_rule_targets),
                [
                    {"rule_id": disabled_rule, "target_id": disabled_target},
                    {"rule_id": shared_rule, "target_id": disabled_target},
                    {"rule_id": shared_rule, "target_id": enabled_target},
                ],
            )
            connection.execute(
                insert(collection_requests).values(
                    id=request_id,
                    rule_id=disabled_rule,
                    rule_version=1,
                    source="bigkinds",
                    mode="incremental",
                    definition=definition,
                    start_date=date(2026, 10, 29),
                    end_date=date(2026, 10, 30),
                )
            )
        assert set(repository.enabled_rules()) >= {shared_rule, unmapped_rule}
        assert disabled_rule not in repository.enabled_rules()
        assert repository.start(request_id, flow_run_id) is None
        with engine.begin() as connection:
            connection.execute(
                update(collection_requests)
                .where(collection_requests.c.id == request_id)
                .values(status="running")
            )
        with pytest.raises(CollectionCancelled):
            repository.check_cancelled(request_id)
    finally:
        with engine.begin() as connection:
            connection.execute(
                delete(collection_requests).where(collection_requests.c.id == request_id)
            )
            connection.execute(
                delete(collection_rule_targets).where(
                    collection_rule_targets.c.rule_id.in_(
                        (disabled_rule, shared_rule, unmapped_rule)
                    )
                )
            )
            connection.execute(
                delete(collection_rule_versions).where(
                    collection_rule_versions.c.rule_id.in_(
                        (disabled_rule, shared_rule, unmapped_rule)
                    )
                )
            )
            connection.execute(
                delete(collection_rules).where(
                    collection_rules.c.id.in_((disabled_rule, shared_rule, unmapped_rule))
                )
            )
            connection.execute(
                delete(analysis_targets).where(
                    analysis_targets.c.id.in_((disabled_target, enabled_target))
                )
            )
