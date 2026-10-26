from prefect import flow, get_run_logger
from prefect.client.orchestration import get_client

from analysis.container import create_analysis_container
from analysis.dispatch import dispatch_one
from analysis.models import AnalysisDispatchSettings
from analysis.repository import AnalysisRepository


@flow(name="dispatch-article-analysis", persist_result=False)
async def dispatch_article_analysis() -> dict[str, int]:
    submitted = 0
    container = create_analysis_container()
    try:
        async with container() as scoped:
            settings = await scoped.get(AnalysisDispatchSettings)
            repository = await scoped.get(AnalysisRepository)
            with get_client(sync_client=True) as client:
                while await dispatch_one(repository, client, settings.deployment_name):
                    submitted += 1
    finally:
        await container.close()
    get_run_logger().info("기사 분석 제출 %s건", submitted)
    return {"submitted": submitted}
