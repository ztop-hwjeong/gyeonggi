from uuid import UUID

import httpx
from prefect import flow, get_run_logger, task
from prefect.cache_policies import NO_CACHE
from prefect.context import FlowRunContext, TaskRunContext

from analysis.cache import PostgresResponseCache
from analysis.client import OpenAIArticleAnalyzer
from analysis.container import create_analysis_container
from analysis.models import AnalysisSettings
from analysis.repository import AnalysisRepository


@task(name="analyze-article", cache_policy=NO_CACHE, persist_result=False, retries=2)
async def analyze_article(source: str, source_id: str, content_hash: str) -> UUID:
    container = create_analysis_container()
    try:
        async with container() as scoped:
            repository = await scoped.get(AnalysisRepository)
            cache = await scoped.get(PostgresResponseCache)
            article = await repository.article(source, source_id, content_hash)
            if article is None:
                raise ValueError("저장된 기사 본문 없음")
            flow_context = FlowRunContext.get()
            task_context = TaskRunContext.get()
            run_id, attempt_id = await repository.claim(
                article,
                flow_context.flow_run.id if flow_context and flow_context.flow_run else None,
                task_context.task_run.id if task_context and task_context.task_run else None,
            )
            try:
                analyzer = await scoped.get(OpenAIArticleAnalyzer)
                draft, usage = await analyzer.analyze(article)
                await cache.acommit()
                await repository.complete(run_id, attempt_id, draft.model_dump(mode="json"), usage)
            except Exception as error:
                await repository.fail(run_id, attempt_id, error)
                raise
            return run_id
    finally:
        await container.close()


@flow(name="analyze-stored-article", persist_result=False)
async def analyze_stored_article(source: str, source_id: str, content_hash: str) -> str:
    run_id = await analyze_article(source, source_id, content_hash)
    await apply_article_analysis(run_id)
    get_run_logger().info("기사 분석 실행 완료: %s", run_id)
    return str(run_id)


@task(name="apply-article-analysis", persist_result=False, retries=2)
async def apply_article_analysis(run_id: UUID) -> None:
    container = create_analysis_container()
    try:
        async with container() as scoped:
            settings = await scoped.get(AnalysisSettings)
            url = f"{str(settings.backend_api_url).rstrip('/')}/analysis/runs/{run_id}/apply"
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(url)
                response.raise_for_status()
    finally:
        await container.close()
