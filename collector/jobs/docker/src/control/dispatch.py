from uuid import uuid4

from prefect.client.orchestration import SyncPrefectClient
from prefect.client.schemas.objects import State, StateType
from prefect.exceptions import ObjectNotFound
from psycopg.types.json import Jsonb

from control.models import ControlSettings
from control.repository import ControlRepository


def enqueue_enabled(repository: ControlRepository) -> int:
    created = 0
    with repository.connect() as conn, conn.transaction():
        rules = conn.execute(
            "SELECT * FROM ops.collection_rules WHERE definition->>'enabled'='true' "
            "ORDER BY updated_at, id FOR UPDATE SKIP LOCKED",
        ).fetchall()
        for rule in rules:
            for source in rule["definition"]["sources"]:
                active = conn.execute(
                    "SELECT 1 FROM ops.collection_requests WHERE rule_id=%s AND source=%s "
                    "AND mode='incremental' "
                    "AND status IN ('queued','submitted','running','cancelling')",
                    (rule["id"], source),
                ).fetchone()
                if active:
                    continue
                conn.execute(
                    "INSERT INTO ops.collection_requests "
                    "(id,rule_id,rule_version,source,mode,definition,start_date,end_date) "
                    "VALUES (%s,%s,%s,%s,'incremental',%s,"
                    "(now() AT TIME ZONE 'Asia/Seoul')::date-1,"
                    "(now() AT TIME ZONE 'Asia/Seoul')::date)",
                    (uuid4(), rule["id"], rule["version"], source, Jsonb(rule["definition"])),
                )
                created += 1
    return created


def submit_one(
    repository: ControlRepository, client: SyncPrefectClient, settings: ControlSettings
) -> bool:
    with repository.connect() as conn, conn.transaction():
        row = conn.execute(
            "SELECT id,mode FROM ops.collection_requests WHERE status='queued' "
            "ORDER BY created_at,id LIMIT 1 FOR UPDATE SKIP LOCKED"
        ).fetchone()
        if row is None:
            return False
        deployment_name = (
            settings.backfill_deployment_name
            if row["mode"] == "backfill"
            else settings.deployment_name
        )
        deployment = client.read_deployment_by_name(deployment_name)
        # Prefect 응답 유실 후 재실행에도 같은 실행을 돌려받는 요청 UUID
        run = client.create_flow_run_from_deployment(
            deployment.id,
            parameters={"request_id": str(row["id"])},
            idempotency_key=f"collection-request:{row['id']}",
        )
        conn.execute(
            "UPDATE ops.collection_requests SET status='submitted',flow_run_id=%s,"
            "error=NULL,updated_at=now() WHERE id=%s",
            (run.id, row["id"]),
        )
        return True


def reconcile(repository: ControlRepository, client: SyncPrefectClient, limit: int) -> None:
    with repository.connect() as conn:
        requests = conn.execute(
            "SELECT id,flow_run_id,status FROM ops.collection_requests "
            "WHERE status IN ('submitted','running','cancelling') AND flow_run_id IS NOT NULL "
            "ORDER BY updated_at LIMIT %s",
            (limit,),
        ).fetchall()
        for request in requests:
            try:
                run = client.read_flow_run(request["flow_run_id"])
            except ObjectNotFound:
                conn.execute(
                    "UPDATE ops.collection_requests SET status='failed',"
                    "error='Prefect 실행 없음',updated_at=now() WHERE id=%s "
                    "AND status IN ('submitted','running','cancelling')",
                    (request["id"],),
                )
                continue
            if run.state is None:
                continue
            if run.state.is_final():
                status = "cancelled" if run.state.type == StateType.CANCELLED else "failed"
                conn.execute(
                    "UPDATE ops.collection_requests SET status=%s,error=%s,updated_at=now() "
                    "WHERE id=%s AND status IN ('submitted','running','cancelling')",
                    (status, "Prefect 실행 종료: " + run.state.type.value, request["id"]),
                )
            elif request["status"] == "cancelling":
                client.set_flow_run_state(
                    run.id, State(type=StateType.CANCELLING, name="Cancelling")
                )
            conn.execute(
                "UPDATE ops.collection_requests SET updated_at=now() WHERE id=%s", (request["id"],)
            )
