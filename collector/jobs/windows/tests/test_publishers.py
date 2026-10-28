import os
from unittest.mock import Mock
from uuid import uuid4

import pytest
from collector_storage.publishers import publisher_code
from sqlalchemy import MetaData, Table, create_engine, insert, select, update

from articles.extraction import ArticleExtractor, ExtractionRejectedError
from articles.models import PublisherIdentity
from articles.storage import DetailRepository
from config import ExtractionSettings


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://WWW.MUNHWA.COM/article/1", "munhwa.com"),
        ("http://munhwa.com/article/2?ref=naver", "munhwa.com"),
        ("https://unknown.example/a", "unknown.example"),
        ("https://news.tvchosun.com/a", "news.tvchosun.com"),
        ("https://n.news.naver.com/mnews/article/001/1234", "naver:001"),
        ("https://news.naver.com/main/read.naver?oid=021&aid=1234", "naver:021"),
        ("https://news.naver.com/", None),
        ("javascript:alert(1)", None),
    ],
)
def test_code_is_derived_from_original_url(url, expected):
    assert publisher_code(url) == expected


def test_unknown_name_does_not_block_body_collection(seed, article_html, repository):
    seed = seed.model_copy(update={"source": "naver_news", "publisher": None})
    result = ArticleExtractor(repository, ExtractionSettings()).extract(
        seed, article_html, str(seed.original_url)
    )
    assert result.evidence.verified
    assert result.publisher is not None and result.publisher.code == "example.org"
    assert result.publisher.name is None
    repository.save_profile.assert_called()


def test_display_name_change_keeps_adaptive_profile(seed, article_html, repository):
    seed = seed.model_copy(update={"source": "naver_news", "publisher": None})
    repository.resolve_publisher.side_effect = None
    repository.resolve_publisher.return_value = PublisherIdentity(code="news", name="처음 이름")
    extractor = ArticleExtractor(repository, ExtractionSettings())
    extractor.extract(seed, article_html, str(seed.original_url))
    repository.resolve_publisher.return_value = PublisherIdentity(code="news", name="변경 이름")
    result = extractor.extract(seed, article_html, str(seed.original_url))
    assert result.method == "adaptive"
    assert result.publisher is not None and result.publisher.name == "변경 이름"


def test_failed_body_never_teaches_adaptive_structure(seed, repository):
    seed = seed.model_copy(update={"source": "naver_news", "publisher": None})
    with pytest.raises(ExtractionRejectedError):
        ArticleExtractor(repository, ExtractionSettings()).extract(
            seed, "<article>오류 화면</article>".encode(), str(seed.original_url)
        )
    repository.save_profile.assert_not_called()


@pytest.mark.skipif("ANALYSIS_TEST_DATABASE_URL" not in os.environ, reason="전용 검증 DB 필요")
def test_database_manages_names_domain_aliases_and_existing_articles():
    engine = create_engine(os.environ["ANALYSIS_TEST_DATABASE_URL"])
    metadata = MetaData()
    publishers = Table("publishers", metadata, schema="dw", autoload_with=engine)
    domains = Table("publisher_domains", metadata, schema="dw", autoload_with=engine)
    search = Table("search_items", metadata, schema="dw", autoload_with=engine)
    articles = Table("articles", metadata, schema="dw", autoload_with=engine)
    repository = DetailRepository(engine, Mock())
    key = uuid4().hex
    domain = f"{key}.example"
    code = "9001"
    try:
        unknown = repository.resolve_publisher(f"https://{domain}/article")
        assert unknown is not None and unknown.code == domain and unknown.name is None
        assert unknown.method == "domain"
        with engine.connect() as connection:
            assert (
                connection.scalar(select(publishers.c.code).where(publishers.c.code == domain))
                is None
            )
        with engine.begin() as connection:
            connection.execute(
                insert(search).values(
                    provider="naver",
                    channel="news",
                    source_id=key,
                    content_hash="listing",
                    data={
                        "title": "기사",
                        "url": f"https://{domain}/article",
                        "publisher_code": domain,
                        "publisher_domain": domain,
                    },
                )
            )
            connection.execute(
                insert(publishers).values(
                    code=code, name="언론사 이름", category_code="online_specialty"
                )
            )
            connection.execute(insert(domains).values(domain=domain, publisher_code=code))
            connection.execute(
                insert(domains).values(domain=f"mobile.{domain}", publisher_code=code)
            )
        resolved = repository.resolve_publisher(f"https://{domain}/article")
        mobile = repository.resolve_publisher(f"https://mobile.{domain}/article")
        assert resolved is not None and mobile is not None
        assert resolved.code == mobile.code == code
        with engine.connect() as connection:
            row = connection.execute(
                select(articles.c.publisher_code, articles.c.publisher)
                .join(
                    search,
                    search.c.article_id == articles.c.id,
                )
                .where(search.c.source_id == key)
            ).one()
        assert (row.publisher_code, row.publisher) == (code, "언론사 이름")
        with engine.begin() as connection:
            connection.execute(
                update(publishers).where(publishers.c.code == code).values(name="수정 이름")
            )
        resolved = repository.resolve_publisher(f"https://{domain}/article")
        assert resolved is not None and resolved.name == "수정 이름"
        with engine.connect() as connection:
            name = connection.execute(
                select(articles.c.publisher)
                .join(
                    search,
                    search.c.article_id == articles.c.id,
                )
                .where(search.c.source_id == key)
            ).scalar_one()
        assert name == "수정 이름"
    finally:
        engine.dispose()


@pytest.mark.skipif("ANALYSIS_TEST_DATABASE_URL" not in os.environ, reason="전용 검증 DB 필요")
def test_naver_publisher_id_can_be_registered_after_listing():
    engine = create_engine(os.environ["ANALYSIS_TEST_DATABASE_URL"])
    metadata = MetaData()
    catalog = Table("publishers", metadata, schema="dw", autoload_with=engine)
    source_codes = Table("publisher_source_codes", metadata, schema="dw", autoload_with=engine)
    search = Table("search_items", metadata, schema="dw", autoload_with=engine)
    articles = Table("articles", metadata, schema="dw", autoload_with=engine)
    key = uuid4().hex
    try:
        with engine.begin() as connection:
            connection.execute(
                insert(search).values(
                    provider="naver",
                    channel="news",
                    source_id=key,
                    content_hash=key,
                    data={
                        "title": "기사",
                        "url": "https://n.news.naver.com/article/998/1234",
                        "publisher_domain": "naver:998",
                        "publisher_code": "naver:998",
                    },
                )
            )
            article_id = connection.scalar(
                select(search.c.article_id).where(search.c.source_id == key)
            )
            assert (
                connection.scalar(
                    select(articles.c.publisher_code).where(articles.c.id == article_id)
                )
                is None
            )
            connection.execute(
                insert(catalog).values(
                    code="9002", name="뒤늦게 등록한 언론사", category_code="online_specialty"
                )
            )
            connection.execute(
                insert(source_codes).values(
                    source="naver", source_code="998", publisher_code="9002"
                )
            )
            row = connection.execute(
                select(articles.c.publisher_code, articles.c.publisher).where(
                    articles.c.id == article_id
                )
            ).one()
            assert (row.publisher_code, row.publisher) == ("9002", "뒤늦게 등록한 언론사")
        resolved = DetailRepository(engine, Mock()).resolve_publisher(
            "https://n.news.naver.com/article/998/1234"
        )
        assert resolved is not None and resolved.code == "9002"
        with engine.begin() as connection:
            connection.execute(
                update(source_codes)
                .where(source_codes.c.source == "naver", source_codes.c.source_code == "998")
                .values(publisher_code="1021")
            )
            row = connection.execute(
                select(articles.c.publisher_code, articles.c.publisher).where(
                    articles.c.id == article_id
                )
            ).one()
            assert (row.publisher_code, row.publisher) == ("1021", "문화일보")
    finally:
        engine.dispose()
