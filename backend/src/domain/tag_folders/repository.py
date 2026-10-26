from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from sqlalchemy import ColumnElement, and_, delete, exists, func, insert, literal, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from domain.analysis.membership import tagged_materials
from domain.analysis.tables import article_topics, topics
from domain.article_workflow.tables import article_inclusions
from domain.collection.tables import material_sources, materials
from domain.events.tables import event_targets
from domain.tag_folders.models import (
    FolderCreate,
    FolderInfo,
    FolderQuery,
    FolderTagAttach,
    FolderTagMove,
    FolderUpdate,
    TagInfo,
    TagQuery,
    UnfiledTagSummary,
)
from domain.tag_folders.tables import folder_tags, folders


class TagFolderError(RuntimeError):
    pass


class TagFolderNotFoundError(TagFolderError):
    pass


class TagFolderConflictError(TagFolderError):
    pass


def folder_descendants(folder_id: UUID):
    tree = select(folders.c.id).where(folders.c.id == folder_id).cte("folder_tree", recursive=True)
    return tree.union_all(select(folders.c.id).join(tree, folders.c.parent_id == tree.c.id))


class TagFolderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @asynccontextmanager
    async def _transaction(self) -> AsyncGenerator[None]:
        try:
            async with self._session.begin():
                yield
        except SQLAlchemyError as error:
            raise TagFolderError("태그 폴더 저장소 연결 실패") from error

    async def _require_folder(self, folder_id: UUID) -> None:
        found = await self._session.scalar(select(folders.c.id).where(folders.c.id == folder_id))
        if found is None:
            raise TagFolderNotFoundError("태그 폴더 없음")

    async def folder_tag_ids(self, folder_id: UUID, include_descendants: bool = True) -> set[str]:
        await self._require_folder(folder_id)
        scope = select(folders.c.id).where(folders.c.id == folder_id)
        if include_descendants:
            scope = select(folder_descendants(folder_id).c.id)
        result = await self._session.scalars(
            select(folder_tags.c.tag_id)
            .select_from(folder_tags.join(topics, topics.c.id == folder_tags.c.tag_id))
            .where(
                folder_tags.c.folder_id.in_(scope),
                topics.c.archived_at.is_(None),
                topics.c.merged_into.is_(None),
            )
        )
        return set(result.all())

    async def unfiled_tag_ids(self) -> set[str]:
        result = await self._session.scalars(
            select(topics.c.id).where(
                topics.c.archived_at.is_(None),
                topics.c.merged_into.is_(None),
                ~exists(select(folder_tags.c.tag_id).where(folder_tags.c.tag_id == topics.c.id)),
            )
        )
        return set(result.all())

    @staticmethod
    def _inclusion_condition(inclusion: str):
        if inclusion == "all":
            return literal(True)
        decision = "include" if inclusion == "included" else "exclude"
        return func.coalesce(article_inclusions.c.decision, "include") == decision

    async def _material_count(
        self, tag_ids: set[str], inclusion: str, kind: str | None = None
    ) -> int:
        if not tag_ids:
            return 0
        statement = (
            select(func.count(func.distinct(materials.c.id)))
            .select_from(
                materials.outerjoin(
                    article_inclusions, article_inclusions.c.article_id == materials.c.id
                )
            )
            .where(
                tagged_materials(tag_ids, kind=kind),
                self._inclusion_condition(inclusion),
            )
        )
        return int((await self._session.scalar(statement)) or 0)

    async def _material_ids_by_tag(self, inclusion: str, kind: str | None) -> dict[str, set[UUID]]:
        linked = (
            article_topics.join(
                material_sources,
                and_(
                    article_topics.c.source == material_sources.c.source,
                    article_topics.c.source_id == material_sources.c.source_id,
                ),
            )
            .join(materials, materials.c.id == material_sources.c.material_id)
            .join(topics, topics.c.id == article_topics.c.topic_id)
            .outerjoin(article_inclusions, article_inclusions.c.article_id == materials.c.id)
        )
        criteria = [
            topics.c.archived_at.is_(None),
            topics.c.merged_into.is_(None),
            self._inclusion_condition(inclusion),
            materials.c.kind.in_(("news", "blog")),
        ]
        if kind is not None:
            criteria.append(materials.c.kind == kind)
        rows = (
            await self._session.execute(
                select(article_topics.c.topic_id, material_sources.c.material_id)
                .select_from(linked)
                .where(*criteria)
                .group_by(article_topics.c.topic_id, material_sources.c.material_id)
                .having(
                    func.bool_or(article_topics.c.origin == "manual_exclude").is_(False),
                    func.bool_or(article_topics.c.origin.in_(("ai", "manual_include"))).is_(True),
                )
            )
        ).all()
        result: dict[str, set[UUID]] = {}
        for tag_id, material_id in rows:
            result.setdefault(tag_id, set()).add(material_id)
        return result

    async def folders(self, query: FolderQuery) -> list[FolderInfo]:
        async with self._transaction():
            rows = list(
                (
                    await self._session.execute(
                        select(folders).order_by(folders.c.name, folders.c.id)
                    )
                ).mappings()
            )
            memberships = (
                await self._session.execute(
                    select(folder_tags.c.folder_id, folder_tags.c.tag_id)
                    .join(topics, topics.c.id == folder_tags.c.tag_id)
                    .where(topics.c.archived_at.is_(None), topics.c.merged_into.is_(None))
                )
            ).all()
            direct: dict[UUID, set[str]] = {}
            for folder_id, tag_id in memberships:
                direct.setdefault(folder_id, set()).add(tag_id)
            children: dict[UUID, list[UUID]] = {}
            for row in rows:
                if row["parent_id"] is not None:
                    children.setdefault(row["parent_id"], []).append(row["id"])
            material_ids = await self._material_ids_by_tag(query.inclusion, query.kind)
            result: list[FolderInfo] = []
            for row in rows:
                tag_ids: set[str] = set()
                visited: set[UUID] = set()
                pending = [row["id"]]
                while pending:
                    current = pending.pop()
                    if current in visited:
                        continue
                    visited.add(current)
                    tag_ids.update(direct.get(current, set()))
                    pending.extend(children.get(current, []))
                attached_materials = set().union(
                    *(material_ids.get(tag_id, set()) for tag_id in tag_ids)
                )
                result.append(
                    FolderInfo(
                        **row,
                        tag_count=len(tag_ids),
                        material_count=len(attached_materials),
                    )
                )
            return result

    async def save_folder(
        self, body: FolderCreate | FolderUpdate, folder_id: UUID | None = None
    ) -> FolderInfo:
        async with self._transaction():
            if body.parent_id is not None:
                await self._require_folder(body.parent_id)
            if folder_id is None:
                folder_id = uuid4()
                await self._session.execute(
                    insert(folders).values(id=folder_id, name=body.name, parent_id=body.parent_id)
                )
            else:
                if body.parent_id == folder_id:
                    raise TagFolderConflictError("자기 자신을 상위 폴더로 지정 불가")
                await self._require_folder(folder_id)
                if body.parent_id is not None:
                    descendants = folder_descendants(folder_id)
                    descendant = await self._session.scalar(
                        select(descendants.c.id).where(descendants.c.id == body.parent_id)
                    )
                    if descendant is not None:
                        raise TagFolderConflictError("하위 폴더로 이동 불가")
                assert isinstance(body, FolderUpdate)
                changed = await self._session.execute(
                    update(folders)
                    .where(folders.c.id == folder_id, folders.c.version == body.version)
                    .values(
                        name=body.name,
                        parent_id=body.parent_id,
                        version=folders.c.version + 1,
                        updated_at=func.now(),
                    )
                    .returning(folders)
                )
                if changed.mappings().one_or_none() is None:
                    raise TagFolderConflictError("태그 폴더가 다른 작업으로 변경됨")
            row = (
                (await self._session.execute(select(folders).where(folders.c.id == folder_id)))
                .mappings()
                .one()
            )
            tag_ids = await self.folder_tag_ids(folder_id)
            return FolderInfo(
                **row,
                tag_count=len(tag_ids),
                material_count=await self._material_count(tag_ids, "all"),
            )

    async def delete_folder(self, folder_id: UUID, version: int) -> None:
        async with self._transaction():
            await self._require_folder(folder_id)
            current_version = await self._session.scalar(
                select(folders.c.version).where(folders.c.id == folder_id).with_for_update()
            )
            if current_version != version:
                raise TagFolderConflictError("태그 폴더가 다른 작업으로 변경됨")
            subtree = select(folder_descendants(folder_id).c.id)
            used_by_event = await self._session.scalar(
                select(event_targets.c.id).where(event_targets.c.folder_id.in_(subtree)).limit(1)
            )
            if used_by_event is not None:
                raise TagFolderConflictError("이벤트에 연결된 폴더 삭제 불가")
            await self._session.execute(delete(folders).where(folders.c.id.in_(subtree)))

    async def attach_tags(self, folder_id: UUID, body: FolderTagAttach) -> None:
        async with self._transaction():
            await self._require_folder(folder_id)
            active_ids = set(
                (
                    await self._session.scalars(
                        select(topics.c.id).where(
                            topics.c.id.in_(body.tag_ids),
                            topics.c.archived_at.is_(None),
                            topics.c.merged_into.is_(None),
                        )
                    )
                ).all()
            )
            if active_ids != set(body.tag_ids):
                raise TagFolderNotFoundError("사용 가능한 태그 없음")
            await self._session.execute(
                pg_insert(folder_tags)
                .values([{"folder_id": folder_id, "tag_id": tag_id} for tag_id in body.tag_ids])
                .on_conflict_do_nothing()
            )

    async def move_tag(self, body: FolderTagMove) -> None:
        async with self._transaction():
            active = await self._session.scalar(
                select(topics.c.id).where(
                    topics.c.id == body.tag_id,
                    topics.c.archived_at.is_(None),
                    topics.c.merged_into.is_(None),
                )
            )
            if active is None:
                raise TagFolderNotFoundError("사용 가능한 태그 없음")
            if body.source_folder_id is None:
                existing = await self._session.scalar(
                    select(folder_tags.c.folder_id)
                    .where(folder_tags.c.tag_id == body.tag_id)
                    .limit(1)
                )
                if existing is not None:
                    raise TagFolderConflictError("태그가 이미 폴더에 편입됨")
            else:
                source = await self._session.scalar(
                    select(folder_tags.c.folder_id)
                    .where(
                        folder_tags.c.folder_id == body.source_folder_id,
                        folder_tags.c.tag_id == body.tag_id,
                    )
                    .with_for_update()
                )
                if source is None:
                    raise TagFolderConflictError("이동할 태그 연결 없음")
            if body.target_folder_id is not None:
                await self._require_folder(body.target_folder_id)
                await self._session.execute(
                    pg_insert(folder_tags)
                    .values(folder_id=body.target_folder_id, tag_id=body.tag_id)
                    .on_conflict_do_nothing()
                )
            if body.source_folder_id is not None:
                await self._session.execute(
                    delete(folder_tags).where(
                        folder_tags.c.folder_id == body.source_folder_id,
                        folder_tags.c.tag_id == body.tag_id,
                    )
                )

    async def detach_tag(self, folder_id: UUID, tag_id: str) -> None:
        async with self._transaction():
            await self._require_folder(folder_id)
            await self._session.execute(
                delete(folder_tags).where(
                    folder_tags.c.folder_id == folder_id, folder_tags.c.tag_id == tag_id
                )
            )

    async def tags(self, query: TagQuery) -> list[TagInfo]:
        async with self._transaction():
            tag_filter: list[ColumnElement[bool]] = [
                topics.c.archived_at.is_(None),
                topics.c.merged_into.is_(None),
            ]
            if query.unfiled:
                tag_ids = await self.unfiled_tag_ids()
                if not tag_ids:
                    return []
                tag_filter.append(topics.c.id.in_(tag_ids))
            if query.folder_id is not None:
                tag_ids = await self.folder_tag_ids(query.folder_id, query.include_descendants)
                if not tag_ids:
                    return []
                tag_filter.append(topics.c.id.in_(tag_ids))
            topic_rows = (
                (
                    await self._session.execute(
                        select(topics).where(*tag_filter).order_by(topics.c.name, topics.c.id)
                    )
                )
                .mappings()
                .all()
            )
            memberships = (
                await self._session.execute(select(folder_tags.c.tag_id, folder_tags.c.folder_id))
            ).all()
            folders_by_tag: dict[str, list[UUID]] = {}
            for tag_id, folder_id in memberships:
                folders_by_tag.setdefault(tag_id, []).append(folder_id)
            material_ids = await self._material_ids_by_tag(query.inclusion, query.kind)
            result: list[TagInfo] = []
            for row in topic_rows:
                tag_id = row["id"]
                result.append(
                    TagInfo(
                        **row,
                        material_count=len(material_ids.get(tag_id, set())),
                        folder_ids=folders_by_tag.get(tag_id, []),
                    )
                )
            return result

    async def unfiled_summary(self, inclusion: str, kind: str | None = None) -> UnfiledTagSummary:
        async with self._transaction():
            tag_ids = await self.unfiled_tag_ids()
            return UnfiledTagSummary(
                tag_count=len(tag_ids),
                material_count=await self._material_count(tag_ids, inclusion, kind),
            )
