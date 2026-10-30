from prefect import flow
from prefect.client.orchestration import get_client

from analysis.container import create_analysis_container
from relevance.dispatch import dispatch_one, recover_expired
from relevance.repository import RelevanceRepository


@flow(name="dispatch-report-relevance", persist_result=False)
async def dispatch_report_relevance() -> dict[str, int]:
    submitted = 0
    container = create_analysis_container()
    try:
        async with container() as scoped:
            repository = await scoped.get(RelevanceRepository)
            with get_client(sync_client=True) as client:
                await recover_expired(repository, client)
                while await dispatch_one(
                    repository, client, "analyze-report-relevance/report-relevance"
                ):
                    submitted += 1
    finally:
        await container.close()
    return {"submitted": submitted}
