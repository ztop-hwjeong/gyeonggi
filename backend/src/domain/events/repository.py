from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from domain.analysis.tables import topics
from domain.events.models import EventCreate, EventInfo, EventQuery, EventTargetInfo, EventUpdate
from domain.events.tables import event_targets, events
from domain.tag_folders.tables import folders


class EventError(RuntimeError):
    pass


class EventNotFoundError(EventError):
    pass


class EventConflictError(EventError):
    pass


class EventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @asynccontextmanager
    async def _transaction(self) -> AsyncGenerator[None]:
        try:
            async with self._session.begin():
                yield
        except IntegrityError as error:
            raise EventConflictError("이벤트 대상이 변경됨") from error
        except SQLAlchemyError as error:
            raise EventError("이벤트 저장소 연결 실패") from error

    async def _validate_targets(self, body: EventCreate, event_id: UUID | None = None) -> None:
        if body.tag_ids:
            active = set(
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
            retained: set[str] = set()
            if event_id is not None:
                retained = set(
                    (
                        await self._session.scalars(
                            select(event_targets.c.tag_id).where(
                                event_targets.c.event_id == event_id,
                                event_targets.c.tag_id.in_(body.tag_ids),
                            )
                        )
                    ).all()
                )
            if active | retained != set(body.tag_ids):
                raise EventNotFoundError("사용 가능한 태그 없음")
        if body.folder_ids:
            available = set(
                (
                    await self._session.scalars(
                        select(folders.c.id).where(folders.c.id.in_(body.folder_ids))
                    )
                ).all()
            )
            if available != set(body.folder_ids):
                raise EventNotFoundError("폴더 없음")

    async def _targets(self, event_ids: list[UUID]) -> dict[UUID, list[EventTargetInfo]]:
        result: dict[UUID, list[EventTargetInfo]] = {event_id: [] for event_id in event_ids}
        if not event_ids:
            return result
        rows = (
            (
                await self._session.execute(
                    select(
                        event_targets.c.event_id,
                        event_targets.c.tag_id,
                        topics.c.name.label("tag_name"),
                        event_targets.c.folder_id,
                        folders.c.name.label("folder_name"),
                    )
                    .outerjoin(topics, topics.c.id == event_targets.c.tag_id)
                    .outerjoin(folders, folders.c.id == event_targets.c.folder_id)
                    .where(event_targets.c.event_id.in_(event_ids))
                    .order_by(event_targets.c.id)
                )
            )
            .mappings()
            .all()
        )
        for row in rows:
            if row["tag_id"] is not None:
                target = EventTargetInfo(kind="tag", id=row["tag_id"], name=row["tag_name"])
            else:
                target = EventTargetInfo(
                    kind="folder", id=str(row["folder_id"]), name=row["folder_name"]
                )
            result[row["event_id"]].append(target)
        return result

    async def _info(self, event_id: UUID) -> EventInfo:
        row = (
            (await self._session.execute(select(events).where(events.c.id == event_id)))
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise EventNotFoundError("이벤트 없음")
        targets = await self._targets([event_id])
        return EventInfo.model_validate({**row, "targets": targets[event_id]})

    async def get(self, event_id: UUID) -> EventInfo:
        async with self._transaction():
            return await self._info(event_id)

    async def list(self, query: EventQuery) -> list[EventInfo]:
        async with self._transaction():
            criteria = []
            if query.q:
                escaped = query.q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                criteria.append(events.c.name.ilike(f"%{escaped}%", escape="\\"))
            if query.occurred_from is not None:
                criteria.append(events.c.occurred_at >= query.occurred_from)
            if query.occurred_until is not None:
                criteria.append(events.c.occurred_at <= query.occurred_until)
            if query.tag_id is not None:
                criteria.append(
                    exists(
                        select(event_targets.c.id).where(
                            event_targets.c.event_id == events.c.id,
                            event_targets.c.tag_id == query.tag_id,
                        )
                    )
                )
            if query.folder_id is not None:
                criteria.append(
                    exists(
                        select(event_targets.c.id).where(
                            event_targets.c.event_id == events.c.id,
                            event_targets.c.folder_id == query.folder_id,
                        )
                    )
                )
            rows = (
                (
                    await self._session.execute(
                        select(events)
                        .where(*criteria)
                        .order_by(events.c.occurred_at.desc(), events.c.id)
                    )
                )
                .mappings()
                .all()
            )
            targets = await self._targets([row["id"] for row in rows])
            return [
                EventInfo.model_validate({**row, "targets": targets[row["id"]]}) for row in rows
            ]

    async def create(self, body: EventCreate) -> EventInfo:
        async with self._transaction():
            await self._validate_targets(body)
            event_id = uuid4()
            await self._session.execute(
                insert(events).values(
                    id=event_id,
                    name=body.name,
                    occurred_at=body.occurred_at,
                )
            )
            await self._replace_targets(event_id, body)
            return await self._info(event_id)

    async def _replace_targets(self, event_id: UUID, body: EventCreate) -> None:
        await self._session.execute(
            delete(event_targets).where(event_targets.c.event_id == event_id)
        )
        targets = [
            *(
                {"event_id": event_id, "tag_id": tag_id, "folder_id": None}
                for tag_id in body.tag_ids
            ),
            *(
                {"event_id": event_id, "tag_id": None, "folder_id": folder_id}
                for folder_id in body.folder_ids
            ),
        ]
        if targets:
            await self._session.execute(insert(event_targets).values(targets))

    async def update(self, event_id: UUID, body: EventUpdate) -> EventInfo:
        async with self._transaction():
            await self._validate_targets(body, event_id)
            changed = await self._session.scalar(
                update(events)
                .where(events.c.id == event_id, events.c.version == body.version)
                .values(
                    name=body.name,
                    occurred_at=body.occurred_at,
                    version=events.c.version + 1,
                    updated_at=func.now(),
                )
                .returning(events.c.id)
            )
            if changed is None:
                found = await self._session.scalar(
                    select(events.c.id).where(events.c.id == event_id)
                )
                if found is None:
                    raise EventNotFoundError("이벤트 없음")
                raise EventConflictError("이벤트 버전 충돌")
            await self._replace_targets(event_id, body)
            return await self._info(event_id)

    async def delete(self, event_id: UUID, version: int) -> None:
        async with self._transaction():
            deleted = await self._session.scalar(
                delete(events)
                .where(events.c.id == event_id, events.c.version == version)
                .returning(events.c.id)
            )
            if deleted is None:
                found = await self._session.scalar(
                    select(events.c.id).where(events.c.id == event_id)
                )
                if found is None:
                    raise EventNotFoundError("이벤트 없음")
                raise EventConflictError("이벤트 버전 충돌")
