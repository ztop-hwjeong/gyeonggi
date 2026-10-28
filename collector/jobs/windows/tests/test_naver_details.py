from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from articles.models import (
    ArticleSeed,
    DetailAttempt,
    Evidence,
    ExtractedArticle,
    PublisherIdentity,
)
from articles.storage import DetailRepository
from flows import details


@pytest.fixture
def detail_context(monkeypatch, repository):
    monkeypatch.setattr(details, "cleanup_browser_tabs", Mock())
    scoped = MagicMock()
    scoped.get.return_value = repository
    container = MagicMock()
    container.return_value.__enter__.return_value = scoped
    monkeypatch.setattr(details, "create_detail_container", Mock(return_value=container))
    monkeypatch.setattr(
        details.FlowRunContext, "get", lambda: SimpleNamespace(flow_run=SimpleNamespace(id=uuid4()))
    )
    monkeypatch.setattr(details, "finish_article", details.finish_article.fn)
    return repository


def test_naver_never_requests_bigkinds_with_its_source_id(monkeypatch, seed, detail_context):
    seed = seed.model_copy(update={"source": "naver_news", "publisher": None})
    stage = Mock(
        side_effect=lambda name, *_: DetailAttempt(stage=name, status="failed", reason="오류")
    )
    monkeypatch.setattr(details, "collect_stage", stage)
    result = details.collect_article_details.fn([seed])
    assert [call.args[0] for call in stage.call_args_list] == [
        "curl_cffi",
        "browser_fetch",
        "browser_rendered",
    ]
    assert result.status == "partial"
    assert result.failed_count == 1


def test_final_result_saves_publisher_and_preserves_naver_timestamp(seed, detail_context):
    provided_at = datetime.fromisoformat("2026-10-28T15:30:00+09:00")
    seed = seed.model_copy(
        update={"source": "naver_news", "publisher": None, "published_at": provided_at}
    )
    extraction = ExtractedArticle(
        title=seed.title,
        text="검증된 기사 본문",
        method="trafilatura",
        publisher=PublisherIdentity(name="경기일보", code="example.org"),
        evidence=Evidence(
            verified=True,
            title_score=100,
            snippet_scores=[100],
            snippet_match_fraction=1,
            body_chars=300,
            reason="제목·요약 문장 일치",
        ),
    )
    result = details.finish_article(
        seed,
        [DetailAttempt(stage="curl_cffi", status="accepted", reason="검증", extraction=extraction)],
        uuid4(),
    )
    assert result.seed.publisher == "경기일보"
    assert result.seed.publisher_code == "example.org"
    assert result.seed.published_at == provided_at
    assert result.seed.source_id == seed.source_id
    assert seed.publisher is None
    detail_context.save_detail.assert_called_once()


def test_pending_flow_handles_empty_queue_without_requests(monkeypatch, detail_context):
    detail_context.pending_naver_news.return_value = []
    stage = Mock()
    monkeypatch.setattr(details, "collect_stage", stage)
    result = details.collect_naver_news_details.fn(limit=10)
    assert result.status == "completed"
    assert result.requested_count == 0
    stage.assert_not_called()
    detail_context.pending_naver_news.assert_called_once_with(10, None)


def test_pending_flow_loads_news_and_disables_bigkinds(monkeypatch, seed, detail_context):
    detail_context.pending_naver_news.return_value = [seed]
    run = Mock()
    monkeypatch.setattr(details, "run_collection", run)
    search_run_id = uuid4()
    details.collect_naver_news_details.fn(limit=20, search_run_id=search_run_id)
    detail_context.pending_naver_news.assert_called_once_with(20, search_run_id)
    run.assert_called_once_with([seed], detail_context, allow_bigkinds_fallback=False)


def test_blog_is_rejected_by_news_detail_contract(seed):
    data = seed.model_dump() | {"source": "naver_blog"}
    with pytest.raises(ValidationError):
        ArticleSeed.model_validate(data)


def test_pending_collection_runs_independently_for_both_news_sources(
    monkeypatch, seed, detail_context
):
    articles = [seed, seed.model_copy(update={"source": "naver_news", "source_id": "naver-new"})]
    detail_context.pending_articles.return_value = articles
    run = Mock()
    monkeypatch.setattr(details, "run_collection", run)
    details.collect_pending_article_details.fn(limit=50)
    run.assert_called_once_with(articles, detail_context)
    detail_context.pending_articles.assert_called_once_with(50)


def test_pending_seed_preserves_original_url_and_provider_time():
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.mappings.return_value.all.return_value = [
        {
            "source_id": "naver-id",
            "source": "naver_news",
            "publisher": None,
            "publisher_code": None,
            "data": {
                "title": "명사 초청 강연",
                "summary": "검색 결과 요약",
                "url": "https://n.news.naver.com/article/001/1234",
                "original_url": "https://publisher.example/news/1",
                "published_at": "2026-10-28T15:30:00+09:00",
            },
        }
    ]
    seed = DetailRepository(engine, Mock()).pending_naver_news(10)[0]
    assert seed.source == "naver_news"
    assert str(seed.original_url) == "https://publisher.example/news/1"
    assert seed.published_at == datetime.fromisoformat("2026-10-28T15:30:00+09:00")
    assert seed.published_on is None
    assert seed.publisher is None
