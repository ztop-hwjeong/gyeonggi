from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from domain.collection.errors import CollectionUnavailableError
from domain.publishers.models import (
    PublisherCategory,
    PublisherDomain,
    PublisherInfo,
    PublisherPage,
    PublisherQuery,
    PublisherSourceCategory,
)
from domain.publishers.tables import (
    categories,
    domains,
    publishers,
    source_categories,
    source_codes,
)


class PublisherRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _rows(self, statement) -> list[dict]:
        try:
            result = await self._session.execute(statement)
            return [dict(row) for row in result.mappings()]
        except SQLAlchemyError as error:
            raise CollectionUnavailableError("언론사 저장소 연결 실패") from error

    async def categories(self) -> list[PublisherCategory]:
        rows = await self._rows(
            select(
                categories.c.code,
                categories.c.name,
                func.count(publishers.c.code).label("publisher_count"),
            )
            .outerjoin(publishers, publishers.c.category_code == categories.c.code)
            .group_by(categories.c.code, categories.c.name, categories.c.sort_order)
            .order_by(categories.c.sort_order, categories.c.code)
        )
        return [PublisherCategory.model_validate(row) for row in rows]

    async def publishers(self, query: PublisherQuery) -> PublisherPage:
        conditions = []
        if query.category_code is not None:
            conditions.append(publishers.c.category_code == query.category_code)
        if query.q:
            conditions.append(
                or_(
                    publishers.c.name.icontains(query.q, autoescape=True),
                    publishers.c.code == query.q,
                    select(source_codes.c.source_code)
                    .where(
                        source_codes.c.publisher_code == publishers.c.code,
                        or_(
                            source_codes.c.source_name.icontains(query.q, autoescape=True),
                            source_codes.c.source_code == query.q,
                        ),
                    )
                    .exists(),
                )
            )
        if query.source:
            conditions.append(
                select(source_codes.c.source_code)
                .where(
                    source_codes.c.publisher_code == publishers.c.code,
                    source_codes.c.source == query.source,
                )
                .exists()
            )
        total = await self._rows(
            select(func.count().label("total")).select_from(publishers).where(*conditions)
        )
        rows = await self._rows(
            select(
                publishers.c.code,
                publishers.c.name,
                publishers.c.category_code,
                categories.c.name.label("category_name"),
                publishers.c.category_source,
            )
            .join(categories, categories.c.code == publishers.c.category_code)
            .where(*conditions)
            .order_by(publishers.c.name, publishers.c.code)
            .offset(query.offset)
            .limit(query.limit)
        )
        mapped = {row["code"]: [] for row in rows}
        sources = {row["code"]: [] for row in rows}
        if mapped:
            for domain in await self._rows(
                select(domains.c.domain, domains.c.publisher_code)
                .where(domains.c.publisher_code.in_(mapped))
                .order_by(domains.c.domain)
            ):
                mapped[domain["publisher_code"]].append(domain["domain"])
            for source in await self._rows(
                select(
                    source_codes.c.publisher_code,
                    source_codes.c.source,
                    source_codes.c.source_code,
                    source_codes.c.source_name,
                    source_codes.c.source_category_code,
                    source_categories.c.name.label("source_category_name"),
                    source_codes.c.source_data["AREA"].astext.label("area"),
                )
                .outerjoin(
                    source_categories,
                    and_(
                        source_categories.c.source == source_codes.c.source,
                        source_categories.c.source_category_code
                        == source_codes.c.source_category_code,
                    ),
                )
                .where(source_codes.c.publisher_code.in_(mapped))
                .order_by(source_codes.c.source, source_codes.c.source_code)
            ):
                sources[source.pop("publisher_code")].append(source)
        return PublisherPage(
            items=[
                PublisherInfo.model_validate(
                    row | {"domains": mapped[row["code"]], "sources": sources[row["code"]]}
                )
                for row in rows
            ],
            total=total[0]["total"],
        )

    async def source_categories(self, source: str | None) -> list[PublisherSourceCategory]:
        statement = (
            select(
                source_categories.c.source,
                source_categories.c.source_category_code.label("code"),
                source_categories.c.name,
                func.count(func.distinct(source_codes.c.publisher_code)).label("publisher_count"),
                func.count(source_codes.c.source_code).label("source_code_count"),
            )
            .outerjoin(
                source_codes,
                and_(
                    source_codes.c.source == source_categories.c.source,
                    source_codes.c.source_category_code == source_categories.c.source_category_code,
                ),
            )
            .group_by(
                source_categories.c.source,
                source_categories.c.source_category_code,
                source_categories.c.name,
                source_categories.c.sort_order,
            )
            .order_by(source_categories.c.source, source_categories.c.sort_order)
        )
        if source:
            statement = statement.where(source_categories.c.source == source)
        rows = await self._rows(statement)
        distribution = (
            select(
                source_codes.c.source,
                source_codes.c.source_category_code,
                categories.c.code,
                categories.c.name,
                func.count(func.distinct(publishers.c.code)).label("publisher_count"),
            )
            .join(publishers, publishers.c.code == source_codes.c.publisher_code)
            .join(categories, categories.c.code == publishers.c.category_code)
            .where(source_codes.c.source_category_code.is_not(None))
            .group_by(
                source_codes.c.source,
                source_codes.c.source_category_code,
                categories.c.code,
                categories.c.name,
            )
            .order_by(categories.c.sort_order, categories.c.code)
        )
        if source:
            distribution = distribution.where(source_codes.c.source == source)
        mapped = {(row["source"], row["code"]): [] for row in rows}
        for row in await self._rows(distribution):
            key = (row.pop("source"), row.pop("source_category_code"))
            mapped[key].append(row)
        return [
            PublisherSourceCategory.model_validate(
                row | {"categories": mapped[row["source"], row["code"]]}
            )
            for row in rows
        ]

    async def domains(self, unmapped: bool) -> list[PublisherDomain]:
        statement = select(
            domains.c.domain,
            domains.c.publisher_code,
            publishers.c.name.label("publisher_name"),
            domains.c.evidence["observed_name"].astext.label("observed_name"),
        ).outerjoin(publishers, publishers.c.code == domains.c.publisher_code)
        if unmapped:
            statement = statement.where(domains.c.publisher_code.is_(None))
        rows = await self._rows(statement.order_by(domains.c.domain))
        return [PublisherDomain.model_validate(row) for row in rows]
