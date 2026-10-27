from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from domain.analysis.registry_models import ArticleTopicOverride
from domain.analysis.tables import topics
from domain.collection.tables import materials
from domain.tag_folders.repository import TagFolderError, TagFolderNotFoundError
from domain.tag_folders.tables import material_tags


class MaterialTagLink(BaseModel):
    material_id: UUID
    tag_id: str
    origin: Literal["ai", "manual_include", "manual_exclude"]


class MaterialTags:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @asynccontextmanager
    async def _transaction(self) -> AsyncGenerator[None]:
        try:
            async with self._session.begin():
                yield
        except SQLAlchemyError as error:
            raise TagFolderError("자료 태그 저장소 연결 실패") from error

    async def _require_material(self, material_id: UUID) -> None:
        found = await self._session.scalar(
            select(materials.c.id).where(
                materials.c.id == material_id, materials.c.kind.in_(("news", "blog"))
            )
        )
        if found is None:
            raise TagFolderNotFoundError("자료 없음")

    async def links(self, material_id: UUID) -> list[MaterialTagLink]:
        async with self._transaction():
            await self._require_material(material_id)
            rows = (
                (
                    await self._session.execute(
                        select(
                            material_tags.c.topic_id,
                            material_tags.c.origin,
                        )
                        .join(topics, topics.c.id == material_tags.c.topic_id)
                        .where(
                            material_tags.c.material_id == material_id,
                            topics.c.archived_at.is_(None),
                            topics.c.merged_into.is_(None),
                        )
                        .order_by(material_tags.c.topic_id)
                    )
                )
                .mappings()
                .all()
            )
            return [
                MaterialTagLink(
                    material_id=material_id,
                    tag_id=row["topic_id"],
                    origin=row["origin"],
                )
                for row in rows
            ]

    async def override(self, material_id: UUID, tag_id: str, body: ArticleTopicOverride) -> None:
        async with self._transaction():
            await self._require_material(material_id)
            active = await self._session.scalar(
                select(topics.c.id).where(
                    topics.c.id == tag_id,
                    topics.c.archived_at.is_(None),
                    topics.c.merged_into.is_(None),
                )
            )
            if active is None:
                raise TagFolderNotFoundError("태그 없음")
            if body.decision == "release":
                await self._session.execute(
                    delete(material_tags).where(
                        material_tags.c.material_id == material_id,
                        material_tags.c.topic_id == tag_id,
                        material_tags.c.origin.in_(("manual_include", "manual_exclude")),
                    )
                )
                return
            statement = insert(material_tags).values(
                material_id=material_id,
                topic_id=tag_id,
                origin="manual_" + body.decision,
            )
            await self._session.execute(
                statement.on_conflict_do_update(
                    index_elements=[material_tags.c.material_id, material_tags.c.topic_id],
                    set_={"origin": statement.excluded.origin, "updated_at": func.now()},
                )
            )
