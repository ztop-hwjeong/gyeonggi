from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query

from domain.publishers.models import (
    PublisherCategory,
    PublisherDomain,
    PublisherPage,
    PublisherQuery,
    PublisherSourceCategory,
)
from domain.publishers.repository import PublisherRepository

router = APIRouter(tags=["publishers"], route_class=DishkaRoute)


@router.get("/publisher-categories")
async def categories(repository: FromDishka[PublisherRepository]) -> list[PublisherCategory]:
    return await repository.categories()


@router.get("/publishers")
async def publishers(
    repository: FromDishka[PublisherRepository], query: Annotated[PublisherQuery, Query()]
) -> PublisherPage:
    return await repository.publishers(query)


@router.get("/publisher-source-categories")
async def source_categories(
    repository: FromDishka[PublisherRepository], source: str | None = None
) -> list[PublisherSourceCategory]:
    return await repository.source_categories(source)


@router.get("/publisher-domains")
async def domains(
    repository: FromDishka[PublisherRepository], unmapped: bool = False
) -> list[PublisherDomain]:
    return await repository.domains(unmapped)
