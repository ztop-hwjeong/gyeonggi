from uuid import UUID

from prefect import flow
from prefect.context import FlowRunContext

from analysis.cache import PostgresResponseCache
from analysis.container import create_analysis_container
from relevance.client import RelevanceAnalyzer
from relevance.repository import RelevanceRepository


@flow(name="analyze-report-relevance", persist_result=False)
async def analyze_report_relevance(run_id: UUID) -> None:
    container = create_analysis_container()
    try:
        async with container() as scoped:
            repository = await scoped.get(RelevanceRepository)
            context = FlowRunContext.get()
            item = await repository.claim(
                run_id, context.flow_run.id if context and context.flow_run else None
            )
            if item is None:
                return
            try:
                analyzer = await scoped.get(RelevanceAnalyzer)
                cache = await scoped.get(PostgresResponseCache)
                draft, usage = await analyzer.analyze(item)
                await repository.complete(item, draft.model_dump(), usage)
                await cache.acommit()
            except Exception as error:
                await repository.fail(run_id, error)
                raise
    finally:
        await container.close()
