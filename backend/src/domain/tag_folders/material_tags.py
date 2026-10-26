from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import and_, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from domain.analysis.registry_models import ArticleTopicOverride
from domain.analysis.tables import article_topic_history, article_topics, topics
from domain.collection.tables import material_sources, materials
from domain.tag_folders.repository import TagFolderError, TagFolderNotFoundError


class MaterialTagLink(BaseModel):
    material_id: UUID
    tag_id: str
    origin: Literal["ai", "manual_include", "manual_exclude", "conflict"]


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

    async def _sources(self, material_id: UUID) -> list[dict]:
        found = await self._session.scalar(
            select(materials.c.id).where(materials.c.id == material_id)
        )
        if found is None:
            raise TagFolderNotFoundError("자료 없음")
        rows = (
            (
                await self._session.execute(
                    select(material_sources.c.source, material_sources.c.source_id)
                    .where(material_sources.c.material_id == material_id)
                    .order_by(material_sources.c.source, material_sources.c.source_id)
                )
            )
            .mappings()
            .all()
        )
        if not rows:
            raise TagFolderNotFoundError("자료 출처 없음")
        return [dict(row) for row in rows]

    async def links(self, material_id: UUID) -> list[MaterialTagLink]:
        async with self._transaction():
            await self._sources(material_id)
            rows = (
                (
                    await self._session.execute(
                        select(
                            article_topics.c.topic_id,
                            func.bool_or(article_topics.c.origin == "manual_include").label(
                                "manual_include"
                            ),
                            func.bool_or(article_topics.c.origin == "manual_exclude").label(
                                "manual_exclude"
                            ),
                        )
                        .join(
                            material_sources,
                            and_(
                                material_sources.c.source == article_topics.c.source,
                                material_sources.c.source_id == article_topics.c.source_id,
                            ),
                        )
                        .join(topics, topics.c.id == article_topics.c.topic_id)
                        .where(
                            material_sources.c.material_id == material_id,
                            topics.c.archived_at.is_(None),
                            topics.c.merged_into.is_(None),
                        )
                        .group_by(article_topics.c.topic_id)
                        .order_by(article_topics.c.topic_id)
                    )
                )
                .mappings()
                .all()
            )
            return [
                MaterialTagLink(
                    material_id=material_id,
                    tag_id=row["topic_id"],
                    origin=(
                        "conflict"
                        if row["manual_include"] and row["manual_exclude"]
                        else "manual_exclude"
                        if row["manual_exclude"]
                        else "manual_include"
                        if row["manual_include"]
                        else "ai"
                    ),
                )
                for row in rows
            ]

    async def override(self, material_id: UUID, tag_id: str, body: ArticleTopicOverride) -> None:
        async with self._transaction():
            sources = await self._sources(material_id)
            active = await self._session.scalar(
                select(topics.c.id).where(
                    topics.c.id == tag_id,
                    topics.c.archived_at.is_(None),
                    topics.c.merged_into.is_(None),
                )
            )
            if active is None:
                raise TagFolderNotFoundError("태그 없음")
            for source in sources:
                source_code, source_id = source["source"], source["source_id"]
                previous = await self._session.scalar(
                    select(article_topics.c.origin).where(
                        article_topics.c.source == source_code,
                        article_topics.c.source_id == source_id,
                        article_topics.c.topic_id == tag_id,
                    )
                )
                if body.decision == "release":
                    await self._session.execute(
                        delete(article_topics).where(
                            article_topics.c.source == source_code,
                            article_topics.c.source_id == source_id,
                            article_topics.c.topic_id == tag_id,
                            article_topics.c.origin.in_(("manual_include", "manual_exclude")),
                        )
                    )
                    current = None if previous != "ai" else previous
                else:
                    current = "manual_" + body.decision
                    statement = insert(article_topics).values(
                        source=source_code,
                        source_id=source_id,
                        article_id=material_id,
                        topic_id=tag_id,
                        origin=current,
                    )
                    await self._session.execute(
                        statement.on_conflict_do_update(
                            index_elements=[
                                article_topics.c.source,
                                article_topics.c.source_id,
                                article_topics.c.topic_id,
                            ],
                            set_={
                                "origin": statement.excluded.origin,
                                "article_id": statement.excluded.article_id,
                                "updated_at": func.now(),
                            },
                        )
                    )
                if previous != current:
                    await self._session.execute(
                        insert(article_topic_history).values(
                            source=source_code,
                            source_id=source_id,
                            original_topic_id=tag_id,
                            resulting_topic_id=tag_id,
                            previous_origin=previous,
                            resulting_origin=current,
                            action="release" if body.decision == "release" else "override",
                        )
                    )
