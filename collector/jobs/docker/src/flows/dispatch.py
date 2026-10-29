from prefect import flow, get_run_logger
from prefect.client.orchestration import get_client

from control.dispatch import enqueue_enabled, reconcile, submit_one
from control.models import ControlSettings
from flows.managed import control_repository


@flow(name="dispatch-collections", persist_result=False)
def dispatch_collections() -> dict:
    settings, repository = ControlSettings(), control_repository()
    submitted = 0
    with get_client(sync_client=True) as client:
        reconcile(repository, client, settings.dispatch_batch_size)
        scheduled = enqueue_enabled(repository)
        for _ in range(settings.dispatch_batch_size):
            if not submit_one(repository, client, settings):
                break
            submitted += 1
    get_run_logger().info("수집 요청 생성 %s건, Prefect 제출 %s건", scheduled, submitted)
    return {"scheduled": scheduled, "submitted": submitted}
