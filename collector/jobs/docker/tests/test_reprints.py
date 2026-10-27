import asyncio
import os
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import psycopg
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from analysis.models import Article
from analysis.repository import AnalysisRepository
from analysis.reprints import ReprintCandidate, ReprintMatch, find_reprints
from flows import analysis


def article(body: str) -> Article:
    return Article(
        article_id=UUID("11111111-1111-1111-1111-111111111111"),
        source="bigkinds",
        source_id="source-1",
        content_hash="a" * 64,
        title="교육정책 기사",
        body=body,
    )


def test_reprints_require_distinct_publishers_and_substantial_body_overlap() -> None:
    body = "경기도교육청이 새 교육정책의 시행 계획과 학교 지원 방안을 발표했다. " * 12
    copied = body.replace(" ", "\n") + "추가 안내"
    candidate_id = UUID("22222222-2222-2222-2222-222222222222")
    unrelated_id = UUID("33333333-3333-3333-3333-333333333333")
    matches = find_reprints(
        article(body),
        "첫 언론사",
        [
            ReprintCandidate(candidate_id, "b" * 64, copied, "다른 언론사"),
            ReprintCandidate(unrelated_id, "c" * 64, body, "첫 언론사"),
            ReprintCandidate(
                unrelated_id, "d" * 64, "학교 행사 일정과 지역 소식. " * 30, "셋째 언론사"
            ),
        ],
    )
    assert len(matches) == 1
    assert matches[0].article_id == candidate_id
    assert matches[0].similarity >= 0.85
    assert find_reprints(article("짧은 본문"), "첫 언론사", []) == []
    assert find_reprints(article(body), None, []) == []


def test_reprint_task_persists_only_detected_pairs(monkeypatch: pytest.MonkeyPatch) -> None:
    body = "경기도교육청이 새 교육정책의 시행 계획과 학교 지원 방안을 발표했다. " * 12
    current = article(body)
    repository = Mock()
    repository.article = AsyncMock(return_value=current)
    repository.reprint_candidates = AsyncMock(
        return_value=(
            "첫 언론사",
            [
                ReprintCandidate(
                    UUID("22222222-2222-2222-2222-222222222222"), "b" * 64, body, "다른 언론사"
                )
            ],
        )
    )
    repository.save_reprints = AsyncMock()

    class Scope:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, kind):
            assert kind is AnalysisRepository
            return repository

    class Container:
        def __call__(self):
            return Scope()

        async def close(self):
            return None

    monkeypatch.setattr(analysis, "create_analysis_container", Container)
    count = asyncio.run(analysis.detect_article_reprints.fn("bigkinds", "source-1", "a" * 64))
    assert count == 1
    saved_article, matches = repository.save_reprints.await_args.args
    assert saved_article == current and len(matches) == 1
    assert matches[0].content_hash == "b" * 64


@pytest.mark.skipif(
    "ANALYSIS_TEST_DATABASE_URL" not in os.environ,
    reason="독립 PostgreSQL 테스트 데이터베이스 필요",
)
def test_reprint_versions_keep_both_content_hash_pairs() -> None:
    dsn = os.environ["ANALYSIS_TEST_DATABASE_URL"]
    suffix = uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as connection:
        first_row = connection.execute(
            "SELECT dw.resolve_article_source('bigkinds',%s,NULL,NULL,'First',"
            "NULL,'Outlet A',NULL,NULL)",
            (f"reprint-a-{suffix}",),
        ).fetchone()
        second_row = connection.execute(
            "SELECT dw.resolve_article_source('naver_news',%s,NULL,NULL,'Second',"
            "NULL,'Outlet B',NULL,NULL)",
            (f"reprint-b-{suffix}",),
        ).fetchone()
        assert first_row is not None and second_row is not None
        first, second = first_row[0], second_row[0]
    current = Article(
        article_id=second,
        source="naver_news",
        source_id=f"reprint-b-{suffix}",
        content_hash="b" * 64,
        title="Second",
        body="Article body",
    )
    engine = create_async_engine(dsn.replace("postgresql://", "postgresql+psycopg://", 1))
    repository = AnalysisRepository(async_sessionmaker(engine))

    async def save_versions() -> None:
        await repository.save_reprints(current, [ReprintMatch(first, "a" * 64, 0.95)])
        await repository.save_reprints(current, [ReprintMatch(first, "c" * 64, 0.91)])
        await engine.dispose()

    asyncio.run(save_versions(), loop_factory=asyncio.SelectorEventLoop)
    with psycopg.connect(dsn) as connection:
        rows = connection.execute(
            "SELECT article_a_id,article_b_id,article_a_content_hash,article_b_content_hash "
            "FROM ops.article_reprints WHERE article_a_id=%s AND article_b_id=%s",
            (min(first, second), max(first, second)),
        ).fetchall()
    assert len(rows) == 2
    assert {row[2:] for row in rows} == {("a" * 64, "b" * 64), ("c" * 64, "b" * 64)}
