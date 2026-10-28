import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from domain.publishers.models import PublisherQuery
from domain.publishers.repository import PublisherRepository
from domain.publishers.tables import domains


@pytest.mark.skipif(not os.environ.get("COLLECTION_TEST_DATABASE_URL"), reason="전용 검증 DB 필요")
def test_unified_categories_and_source_catalog_preserve_original_metadata():
    async def check():
        engine = create_async_engine(os.environ["COLLECTION_TEST_DATABASE_URL"])
        try:
            async with AsyncSession(engine) as session:
                repository = PublisherRepository(session)
                categories = await repository.categories()
                assert {row.code: row.name for row in categories} == {
                    "wire": "통신사",
                    "general_daily": "종합일간지",
                    "economic": "경제지",
                    "broadcast": "방송사",
                    "online_specialty": "온라인 뉴스/전문지",
                }
                expected = {
                    "연합뉴스": ("1001", "wire"),
                    "뉴스1": ("1421", "wire"),
                    "조선일보": ("1023", "general_daily"),
                    "한국경제": ("1015", "economic"),
                    "KBS": ("1056", "broadcast"),
                    "뉴데일리": ("2005", "online_specialty"),
                }
                for name, (code, category_code) in expected.items():
                    page = await repository.publishers(PublisherQuery(q=code))
                    assert page.total == 1
                    assert (page.items[0].name, page.items[0].category_code) == (
                        name,
                        category_code,
                    )

                news1 = (await repository.publishers(PublisherQuery(q="1421"))).items[0]
                assert any(
                    source.source == "reference"
                    and source.source_category_code == "2"
                    and source.source_category_name == "방송/통신"
                    for source in news1.sources
                )
                source_categories = await repository.source_categories("reference")
                mixed = next(item for item in source_categories if item.code == "2")
                assert mixed.name == "방송/통신"
                assert {item.code for item in mixed.categories} >= {
                    "wire",
                    "broadcast",
                    "online_specialty",
                }

                bigkinds = await repository.publishers(
                    PublisherQuery(source="bigkinds", limit=1000)
                )
                assert bigkinds.total == len(bigkinds.items) == 104
                regional_daily = (await repository.publishers(PublisherQuery(q="01620001"))).items[
                    0
                ]
                regional_weekly = (await repository.publishers(PublisherQuery(q="05300152"))).items[
                    0
                ]
                assert regional_daily.name == "광남일보"
                assert regional_weekly.name == "설악신문"
                assert regional_daily.category_code == "general_daily"
                assert regional_weekly.category_code == "online_specialty"
                assert any(
                    item.source == "bigkinds" and item.source_category_code == "30"
                    for item in regional_daily.sources
                )
                assert any(
                    item.source == "bigkinds" and item.source_category_code == "31"
                    for item in regional_weekly.sources
                )
        finally:
            await engine.dispose()

    asyncio.run(check())


@pytest.mark.skipif(not os.environ.get("COLLECTION_TEST_DATABASE_URL"), reason="전용 검증 DB 필요")
def test_duplicate_and_bigkinds_aliases_resolve_to_one_canonical_publisher():
    async def check():
        engine = create_async_engine(os.environ["COLLECTION_TEST_DATABASE_URL"])
        try:
            async with AsyncSession(engine) as session:
                repository = PublisherRepository(session)
                weekly = await repository.publishers(PublisherQuery(q="주간한국"))
                assert weekly.total == 1
                assert weekly.items[0].code == "1042"
                assert {
                    source.source_code
                    for source in weekly.items[0].sources
                    if source.source == "reference"
                } >= {"1042", "2723"}
                by_original_code = await repository.publishers(PublisherQuery(q="2723"))
                assert by_original_code.total == 1
                assert by_original_code.items[0].code == "1042"

                metro = await repository.publishers(PublisherQuery(q="메트로경제"))
                assert metro.total == 1
                assert (metro.items[0].code, metro.items[0].category_code) == ("2286", "economic")
                assert any(
                    source.source == "bigkinds"
                    and source.source_code == "02100401"
                    and source.source_name == "메트로경제"
                    for source in metro.items[0].sources
                )
                by_bigkinds_code = await repository.publishers(PublisherQuery(q="02100401"))
                assert by_bigkinds_code.total == 1
                assert by_bigkinds_code.items[0].code == "2286"
                assert not (await repository.publishers(PublisherQuery(q="%"))).items
        finally:
            await engine.dispose()

    asyncio.run(check())


@pytest.mark.skipif(not os.environ.get("COLLECTION_TEST_DATABASE_URL"), reason="전용 검증 DB 필요")
def test_unmapped_domain_is_kept_without_a_fake_publisher_code():
    async def check():
        engine = create_async_engine(os.environ["COLLECTION_TEST_DATABASE_URL"])
        try:
            async with engine.connect() as connection, connection.begin():
                async with AsyncSession(
                    bind=connection, join_transaction_mode="create_savepoint"
                ) as session:
                    domain = f"{uuid4().hex}.example"
                    await session.execute(
                        insert(domains).values(
                            domain=domain,
                            publisher_code=None,
                            evidence={"observed_name": "새 매체"},
                        )
                    )
                    repository = PublisherRepository(session)
                    pending = {row.domain: row for row in await repository.domains(True)}
                    assert pending[domain].publisher_code is None
                    assert pending[domain].publisher_name is None
                    assert pending[domain].observed_name == "새 매체"
                    assert (await repository.publishers(PublisherQuery(q="새 매체"))).total == 0
        finally:
            await engine.dispose()

    asyncio.run(check())
