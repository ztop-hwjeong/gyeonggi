import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from domain.analysis.registry import TopicRegistry
from domain.analysis.registry_models import Topic
from domain.events.models import EventCreate, EventQuery, EventUpdate
from domain.events.repository import EventConflictError, EventNotFoundError, EventRepository
from domain.tag_folders.models import FolderCreate
from domain.tag_folders.repository import TagFolderConflictError, TagFolderRepository


def test_event_requires_aware_time_and_only_core_fields() -> None:
    base = {
        "name": "정책 발표",
        "occurred_at": "2026-10-26T10:00:00+09:00",
    }
    assert EventCreate.model_validate(base).occurred_at.utcoffset() == timedelta(hours=9)
    with pytest.raises(ValidationError):
        EventCreate.model_validate({**base, "occurred_at": "2026-10-26T10:00:00"})
    with pytest.raises(ValidationError):
        EventCreate.model_validate({**base, "event_type": "press_release"})
    with pytest.raises(ValidationError):
        EventCreate.model_validate({**base, "comparison_days": 7})
    with pytest.raises(ValidationError):
        EventCreate.model_validate({**base, "reference_urls": []})
    with pytest.raises(ValidationError):
        EventCreate.model_validate({**base, "description": "설명"})
    with pytest.raises(ValidationError):
        EventCreate.model_validate({**base, "tag_ids": ["same", "same"]})


@pytest.mark.skipif(
    not os.environ.get("ANALYSIS_TEST_DATABASE_URL"),
    reason="독립 PostgreSQL 테스트 데이터베이스 필요",
)
def test_event_targets_filters_versions_and_restricted_folder_delete() -> None:
    async def check() -> None:
        engine = create_async_engine(os.environ["ANALYSIS_TEST_DATABASE_URL"])
        factory = async_sessionmaker(engine, expire_on_commit=False)
        marker = uuid4().hex[:12]
        tag_a, tag_b = f"event-a-{marker}", f"event-b-{marker}"
        occurred = datetime(2026, 10, 26, 10, tzinfo=UTC)
        try:
            async with factory() as session:
                await TopicRegistry(session).ensure_topics(
                    [
                        Topic(id=tag_a, name=f"정책 {marker}"),
                        Topic(id=tag_b, name=f"발표 {marker}"),
                    ]
                )
                folders = TagFolderRepository(session)
                parent = await folders.save_folder(FolderCreate(name=f"정책 {marker}"))
                folder = await folders.save_folder(
                    FolderCreate(name=f"교육 {marker}", parent_id=parent.id)
                )
                repository = EventRepository(session)
                body = EventCreate(
                    name=f"교육 정책 발표 {marker}",
                    occurred_at=occurred,
                    tag_ids=[tag_a, tag_b],
                    folder_ids=[folder.id],
                )
                created = await repository.create(body)
                assert created.version == 1
                assert {(target.kind, target.id) for target in created.targets} == {
                    ("tag", tag_a),
                    ("tag", tag_b),
                    ("folder", str(folder.id)),
                }
                assert {target.name for target in created.targets} == {
                    f"정책 {marker}",
                    f"발표 {marker}",
                    f"교육 {marker}",
                }
                assert (await repository.get(created.id)).id == created.id
                assert [item.id for item in await repository.list(EventQuery(tag_id=tag_a))] == [
                    created.id
                ]
                assert [
                    item.id for item in await repository.list(EventQuery(folder_id=folder.id))
                ] == [created.id]
                assert [
                    item.id
                    for item in await repository.list(
                        EventQuery(
                            q=marker,
                            occurred_from=occurred - timedelta(days=1),
                            occurred_until=occurred + timedelta(days=1),
                        )
                    )
                ] == [created.id]
                assert (
                    await repository.list(EventQuery(occurred_from=occurred + timedelta(days=1)))
                    == []
                )
                with pytest.raises(TagFolderConflictError):
                    await folders.delete_folder(folder.id, folder.version)
                with pytest.raises(TagFolderConflictError):
                    await folders.delete_folder(parent.id, parent.version)
                assert (await repository.get(created.id)).id == created.id
                updated = await repository.update(
                    created.id,
                    EventUpdate(**body.model_dump(exclude={"tag_ids"}), tag_ids=[tag_b], version=1),
                )
                assert updated.version == 2
                assert {target.id for target in updated.targets} == {tag_b, str(folder.id)}
                await TopicRegistry(session).archive(tag_b)
                retained = await repository.update(
                    created.id,
                    EventUpdate(
                        **body.model_dump(exclude={"tag_ids"}),
                        tag_ids=[tag_b],
                        version=2,
                    ),
                )
                assert retained.version == 3
                assert {target.id for target in retained.targets} == {tag_b, str(folder.id)}
                with pytest.raises(EventConflictError):
                    await repository.update(created.id, EventUpdate(**body.model_dump(), version=1))
                with pytest.raises(EventNotFoundError):
                    await repository.create(body.model_copy(update={"tag_ids": ["missing-tag"]}))
                with pytest.raises(EventConflictError):
                    await repository.delete(created.id, 1)
                await repository.delete(created.id, 3)
                with pytest.raises(EventNotFoundError):
                    await repository.get(created.id)
                await folders.delete_folder(parent.id, parent.version)
        finally:
            await engine.dispose()

    asyncio.run(check())
