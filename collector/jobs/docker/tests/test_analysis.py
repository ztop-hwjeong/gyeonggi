import asyncio
from typing import cast
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from langchain_core.messages import AIMessage
from pydantic import SecretStr, ValidationError
from sqlalchemy.engine import Engine

from analysis.cache import PostgresResponseCache
from analysis.client import MODEL, AnalysisError, OpenAIArticleAnalyzer
from analysis.container import create_analysis_container
from analysis.models import Article, ModelDraft
from analysis.repository import AnalysisRepository
from flows import analysis


def article() -> Article:
    return Article(
        article_id=UUID("11111111-1111-1111-1111-111111111111"),
        source="test",
        source_id="article/1",
        content_hash="a" * 64,
        title="경기도교육청 정책 발표",
        body="경기도교육청이 정책을 발표했다.",
    )


@pytest.fixture(autouse=True)
def backend_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BACKEND_API_URL", "http://backend:8000")


def task_container(monkeypatch: pytest.MonkeyPatch, repository: Mock, analyzer: Mock, cache: Mock):
    class Scope:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, kind):
            return {
                AnalysisRepository: repository,
                PostgresResponseCache: cache,
                OpenAIArticleAnalyzer: analyzer,
            }[kind]

    class Container:
        def __call__(self):
            return Scope()

        async def close(self):
            return None

    monkeypatch.setattr(analysis, "create_analysis_container", Container)


def test_single_article_analysis_saves_raw_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = Mock()
    repository.article = AsyncMock(return_value=article())
    repository.claim = AsyncMock(return_value=(uuid4(), 1))
    repository.complete = AsyncMock()
    repository.fail = AsyncMock()
    draft = ModelDraft(tags=["교육정책"], sentiment="중립")

    analyzer = Mock(analyze=AsyncMock(return_value=(draft, {"total_tokens": 10})))
    cache = Mock(acommit=AsyncMock())
    task_container(monkeypatch, repository, analyzer, cache)
    run_id = asyncio.run(analysis.analyze_article.fn("test", "article/1", "a" * 64))
    assert run_id == repository.claim.return_value[0]
    analyzer.analyze.assert_awaited_once_with(article())
    cache.acommit.assert_awaited_once()
    repository.complete.assert_awaited_once_with(
        run_id, 1, draft.model_dump(mode="json"), {"total_tokens": 10}
    )
    repository.fail.assert_not_awaited()
    repository.topics.assert_not_called()


def test_analysis_error_marks_run_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = Mock()
    repository.article = AsyncMock(return_value=article())
    repository.claim = AsyncMock(return_value=(uuid4(), 1))
    repository.complete = AsyncMock()
    repository.fail = AsyncMock()

    analyzer = Mock(analyze=AsyncMock(side_effect=AnalysisError("분석 미완료")))
    cache = Mock(acommit=AsyncMock())
    task_container(monkeypatch, repository, analyzer, cache)
    with pytest.raises(AnalysisError, match="분석 미완료"):
        asyncio.run(analysis.analyze_article.fn("test", "article/1", "a" * 64))
    repository.fail.assert_awaited_once()
    cache.acommit.assert_not_awaited()


def test_langchain_receives_one_article_and_structured_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = ModelDraft(tags=["교육정책"], sentiment="")
    calls: list[dict] = []

    class Client:
        def __init__(self, **kwargs) -> None:
            calls.append(kwargs)

        def with_structured_output(self, schema, **kwargs):
            assert schema is ModelDraft
            assert kwargs == {"method": "json_schema", "include_raw": True, "strict": True}
            return self

        async def ainvoke(self, messages):
            calls.append({"messages": messages})
            return {"parsed": draft, "parsing_error": None, "raw": AIMessage(content="")}

    monkeypatch.setattr("analysis.client.ChatOpenAI", Client)
    result, usage = asyncio.run(
        OpenAIArticleAnalyzer(
            SecretStr("test"), PostgresResponseCache(cast(Engine, Mock()))
        ).analyze(article())
    )
    assert result == draft and usage["total_tokens"] is None
    assert calls[0]["model"] == MODEL
    prompt = str(calls[1]["messages"][1].content)
    assert '"title"' in prompt and '"body"' in prompt and '"topics"' not in prompt
    assert "article/1" not in prompt and "11111111" not in prompt


def test_tags_are_cleaned_without_extra_model_fields() -> None:
    draft = ModelDraft(tags=[" 정책  개선 ", "정책 개선", "학교폭력"], sentiment="")
    assert draft.model_dump() == {"tags": ["정책 개선", "학교폭력"], "sentiment": ""}
    with pytest.raises(ValidationError):
        ModelDraft(tags=[" "], sentiment="")
    with pytest.raises(ValidationError):
        ModelDraft(tags=["x" * 81], sentiment="")
    assert set(ModelDraft.model_json_schema()["properties"]) == {"tags", "sentiment"}


def test_dishka_loads_database_secret_asynchronously(monkeypatch: pytest.MonkeyPatch) -> None:
    async def load(name: str):
        assert name in ("collector-postgres-password", "openai-api-key")
        return Mock(
            get=Mock(
                return_value="test-password" if name.startswith("collector") else "test-api-key"
            )
        )

    from collector_storage.config import DatabaseSettings

    from analysis import container as wiring

    monkeypatch.setenv("DATABASE_HOST", "localhost")
    monkeypatch.setenv("DATABASE_PORT", "5432")
    monkeypatch.setenv("DATABASE_NAME", "test")
    monkeypatch.setenv("DATABASE_USER", "test")
    monkeypatch.setenv("DATABASE_PASSWORD_BLOCK", "collector-postgres-password")
    monkeypatch.setattr(wiring.Secret, "aload", load)

    async def check() -> None:
        container = create_analysis_container()
        try:
            async with container() as scoped:
                settings = await scoped.get(DatabaseSettings)
                assert settings.database_name == "test"
                credentials = await scoped.get(wiring.DatabaseCredentials)
                assert credentials.password.get_secret_value() == "test-password"
                assert isinstance(await scoped.get(AnalysisRepository), AnalysisRepository)
                assert isinstance(await scoped.get(PostgresResponseCache), PostgresResponseCache)
                assert isinstance(await scoped.get(OpenAIArticleAnalyzer), OpenAIArticleAnalyzer)
        finally:
            await container.close()

    asyncio.run(check())


def test_completed_analysis_still_applies_in_separate_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = uuid4()
    calls: list[str] = []

    async def completed(source, source_id, content_hash):
        calls.append("analysis")
        return run_id

    async def apply(value):
        assert value == run_id
        calls.append("apply")

    monkeypatch.setattr(analysis, "analyze_article", completed)
    monkeypatch.setattr(analysis, "apply_article_analysis", apply)
    monkeypatch.setattr(analysis, "get_run_logger", Mock(return_value=Mock()))

    assert asyncio.run(analysis.analyze_stored_article.fn("test", "article/1", "a" * 64)) == str(
        run_id
    )
    assert calls == ["analysis", "apply"]


def test_apply_task_posts_to_backend_without_model_call(monkeypatch: pytest.MonkeyPatch) -> None:
    posted: list[str] = []

    class Client:
        def __init__(self, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def post(self, url):
            posted.append(url)
            return Mock()

    monkeypatch.setattr(analysis.httpx, "AsyncClient", Client)
    run_id = uuid4()
    asyncio.run(analysis.apply_article_analysis.fn(run_id))
    assert posted == [f"http://backend:8000/analysis/runs/{run_id}/apply"]
