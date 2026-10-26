import asyncio
import json
import os
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from domain.analysis.registry import TopicRegistry
from domain.analysis.registry_models import ArticleTopicOverride, Topic, TopicMerge
from domain.collection.models import MaterialKind, MaterialQuery
from domain.collection.reporting import CollectionReporting
from domain.collection.tables import materials
from domain.tag_folders.material_tags import MaterialTags
from domain.tag_folders.models import (
    FolderCreate,
    FolderQuery,
    FolderTagAttach,
    FolderTagMove,
    FolderUpdate,
    TagQuery,
)
from domain.tag_folders.repository import (
    TagFolderConflictError,
    TagFolderNotFoundError,
    TagFolderRepository,
)


@pytest.mark.skipif(
    not os.environ.get("ANALYSIS_TEST_DATABASE_URL"),
    reason="독립 PostgreSQL 테스트 데이터베이스 필요",
)
def test_folder_counts_unfiled_and_manual_membership() -> None:
    async def check() -> None:
        engine = create_async_engine(os.environ["ANALYSIS_TEST_DATABASE_URL"])
        factory = async_sessionmaker(engine, expire_on_commit=False)
        marker = uuid4().hex
        source_ids = [f"{marker}-{index}" for index in range(3)]
        try:
            async with factory() as session:
                async with session.begin():
                    for source_id in source_ids:
                        await session.execute(
                            text(
                                "INSERT INTO dw.news_items(source,source_id,data) "
                                "VALUES ('bigkinds',:source_id,CAST(:data AS jsonb))"
                            ),
                            {
                                "source_id": source_id,
                                "data": json.dumps(
                                    {
                                        "title": f"태그 폴더 {source_id}",
                                        "original_url": f"https://example.test/{source_id}",
                                    },
                                    ensure_ascii=False,
                                ),
                            },
                        )
                material_ids = list(
                    (
                        await session.scalars(
                            select(materials.c.id)
                            .where(materials.c.title.like(f"%{marker}%"))
                            .order_by(materials.c.title)
                        )
                    ).all()
                )
                assert len(material_ids) == 3
                await session.rollback()
                registry = TopicRegistry(session)
                alpha, beta, gamma = (f"alpha-{marker}", f"beta-{marker}", f"gamma-{marker}")
                await registry.ensure_topics(
                    [
                        Topic(id=alpha, name=f"알파 {marker}", description=""),
                        Topic(id=beta, name=f"베타 {marker}", description=""),
                        Topic(id=gamma, name=f"감마 {marker}", description=""),
                    ]
                )
                await registry.sync_article_topics("bigkinds", source_ids[0], [alpha, beta])
                await registry.sync_article_topics("bigkinds", source_ids[1], [alpha, gamma])
                await registry.override_canonical_article_topic(
                    material_ids[0], alpha, ArticleTopicOverride(decision="exclude")
                )
                folders = TagFolderRepository(session)
                root = await folders.save_folder(FolderCreate(name=f"상위 {marker}"))
                child = await folders.save_folder(
                    FolderCreate(name=f"하위 {marker}", parent_id=root.id)
                )
                await folders.attach_tags(root.id, FolderTagAttach(tag_ids=[alpha]))
                await folders.attach_tags(child.id, FolderTagAttach(tag_ids=[beta]))
                listed = {folder.id: folder for folder in await folders.folders(FolderQuery())}
                assert listed[root.id].tag_count == 2
                assert listed[root.id].material_count == 2
                assert listed[child.id].material_count == 1
                unfiled = await folders.tags(TagQuery(unfiled=True))
                scoped_unfiled = [tag for tag in unfiled if tag.id in {alpha, beta, gamma}]
                assert {tag.id for tag in scoped_unfiled} == {gamma}
                assert scoped_unfiled[0].material_count == 1
                summary_before_merge = await folders.unfiled_summary("all")
                with pytest.raises(TagFolderConflictError):
                    await folders.save_folder(
                        FolderUpdate(name=root.name, parent_id=child.id, version=root.version),
                        root.id,
                    )
                await registry.merge(alpha, TopicMerge(target_id=beta))
                assert await folders.folder_tag_ids(root.id, include_descendants=False) == {beta}
                await session.rollback()
                assert {
                    tag.id
                    for tag in await folders.tags(TagQuery(unfiled=True))
                    if tag.id in {alpha, beta, gamma}
                } == {gamma}
                summary = await folders.unfiled_summary("all")
                assert summary == summary_before_merge
        finally:
            await engine.dispose()

    asyncio.run(check())


@pytest.mark.skipif(
    not os.environ.get("ANALYSIS_TEST_DATABASE_URL"),
    reason="독립 PostgreSQL 테스트 데이터베이스 필요",
)
def test_blog_tag_counts_match_material_drilldown() -> None:
    async def check() -> None:
        engine = create_async_engine(os.environ["ANALYSIS_TEST_DATABASE_URL"])
        factory = async_sessionmaker(engine, expire_on_commit=False)
        marker = uuid4().hex
        tag_id = f"posts-{marker}"
        try:
            async with factory() as session:
                async with session.begin():
                    for index, channel in enumerate(("blog", "blog", "blog")):
                        await session.execute(
                            text(
                                "INSERT INTO dw.search_items"
                                "(provider,channel,source_id,content_hash,data) "
                                "VALUES ('naver',:channel,:source_id,:hash,CAST(:data AS jsonb))"
                            ),
                            {
                                "channel": channel,
                                "source_id": f"{marker}-{index}",
                                "hash": f"{marker}-{index}",
                                "data": json.dumps(
                                    {
                                        "title": f"자료 {marker} {index}",
                                        "summary": "교육 소식",
                                        "url": f"https://example.test/{channel}/{marker}/{index}",
                                    },
                                    ensure_ascii=False,
                                ),
                            },
                        )
                rows = (
                    await session.execute(
                        select(materials.c.id, materials.c.kind)
                        .where(materials.c.title.like(f"%{marker}%"))
                        .order_by(materials.c.kind, materials.c.id)
                    )
                ).all()
                await session.rollback()
                assert sorted(kind for _, kind in rows) == ["blog", "blog", "blog"]
                await TopicRegistry(session).ensure_topics(
                    [Topic(id=tag_id, name=f"교육 글 {marker}")]
                )
                material_tags = MaterialTags(session)
                for material_id, _ in rows:
                    await material_tags.override(
                        material_id, tag_id, ArticleTopicOverride(decision="include")
                    )
                    assert (await material_tags.links(material_id))[0].origin == "manual_include"
                folders = TagFolderRepository(session)
                folder = await folders.save_folder(FolderCreate(name=f"글 폴더 {marker}"))
                await folders.attach_tags(folder.id, FolderTagAttach(tag_ids=[tag_id]))
                reporting = CollectionReporting(session)
                scopes: list[tuple[MaterialKind | None, int]] = [
                    (None, 3),
                    ("blog", 3),
                    ("news", 0),
                ]
                for kind, expected in scopes:
                    tag = next(
                        item
                        for item in await folders.tags(TagQuery(kind=kind))
                        if item.id == tag_id
                    )
                    scoped = next(
                        item
                        for item in await folders.folders(FolderQuery(kind=kind))
                        if item.id == folder.id
                    )
                    page = await reporting.materials(MaterialQuery(kind=kind, folder_id=folder.id))
                    assert tag.material_count == scoped.material_count == page.total == expected
                    assert len(page.items) == expected
                    await session.rollback()
                blog_id = next(material_id for material_id, kind in rows if kind == "blog")
                await material_tags.override(
                    blog_id, tag_id, ArticleTopicOverride(decision="exclude")
                )
                assert (
                    await reporting.materials(MaterialQuery(kind="blog", tag_id=tag_id))
                ).total == 2
                await session.rollback()
                assert (
                    next(
                        item
                        for item in await folders.tags(TagQuery(kind="blog"))
                        if item.id == tag_id
                    ).material_count
                    == 2
                )
        finally:
            await engine.dispose()

    asyncio.run(check())


def test_tag_move_requires_distinct_explicit_locations() -> None:
    with pytest.raises(ValidationError):
        FolderTagMove(tag_id="tag", source_folder_id=None, target_folder_id=None)
    same = uuid4()
    with pytest.raises(ValidationError):
        FolderTagMove(tag_id="tag", source_folder_id=same, target_folder_id=same)


@pytest.mark.skipif(
    not os.environ.get("ANALYSIS_TEST_DATABASE_URL"),
    reason="독립 PostgreSQL 테스트 데이터베이스 필요",
)
def test_atomic_tag_move_preserves_other_folders_and_delete_preserves_tag() -> None:
    async def check() -> None:
        engine = create_async_engine(os.environ["ANALYSIS_TEST_DATABASE_URL"])
        factory = async_sessionmaker(engine, expire_on_commit=False)
        marker = uuid4().hex[:12]
        tag_id = f"move-{marker}"
        try:
            async with factory() as session:
                registry = TopicRegistry(session)
                await registry.ensure_topics([Topic(id=tag_id, name=f"이동 {marker}")])
                folders = TagFolderRepository(session)
                source = await folders.save_folder(FolderCreate(name=f"출발 {marker}"))
                target = await folders.save_folder(FolderCreate(name=f"도착 {marker}"))
                other = await folders.save_folder(FolderCreate(name=f"다른 {marker}"))
                await folders.attach_tags(source.id, FolderTagAttach(tag_ids=[tag_id]))
                await folders.attach_tags(other.id, FolderTagAttach(tag_ids=[tag_id]))
                await folders.move_tag(
                    FolderTagMove(
                        tag_id=tag_id,
                        source_folder_id=source.id,
                        target_folder_id=target.id,
                    )
                )
                assert await folders.folder_tag_ids(source.id) == set()
                assert await folders.folder_tag_ids(target.id) == {tag_id}
                assert await folders.folder_tag_ids(other.id) == {tag_id}
                await session.rollback()
                with pytest.raises(TagFolderConflictError):
                    await folders.move_tag(
                        FolderTagMove(
                            tag_id=tag_id,
                            source_folder_id=source.id,
                            target_folder_id=other.id,
                        )
                    )
                with pytest.raises(TagFolderNotFoundError):
                    await folders.move_tag(
                        FolderTagMove(
                            tag_id=tag_id,
                            source_folder_id=target.id,
                            target_folder_id=UUID(int=0),
                        )
                    )
                assert await folders.folder_tag_ids(target.id) == {tag_id}
                await session.rollback()
                await folders.move_tag(
                    FolderTagMove(
                        tag_id=tag_id,
                        source_folder_id=target.id,
                        target_folder_id=None,
                    )
                )
                assert await folders.folder_tag_ids(other.id) == {tag_id}
                await session.rollback()
                await folders.move_tag(
                    FolderTagMove(
                        tag_id=tag_id,
                        source_folder_id=other.id,
                        target_folder_id=None,
                    )
                )
                assert tag_id in await folders.unfiled_tag_ids()
                await session.rollback()
                await folders.move_tag(
                    FolderTagMove(
                        tag_id=tag_id,
                        source_folder_id=None,
                        target_folder_id=source.id,
                    )
                )
                with pytest.raises(TagFolderConflictError):
                    await folders.move_tag(
                        FolderTagMove(
                            tag_id=tag_id,
                            source_folder_id=None,
                            target_folder_id=target.id,
                        )
                    )
                await folders.delete_folder(source.id, source.version)
                assert tag_id in await folders.unfiled_tag_ids()
                await session.rollback()
                assert tag_id in {topic.id for topic in await registry.topics()}
        finally:
            await engine.dispose()

    asyncio.run(check())


@pytest.mark.skipif(
    not os.environ.get("ANALYSIS_TEST_DATABASE_URL"),
    reason="독립 PostgreSQL 테스트 데이터베이스 필요",
)
def test_delete_folder_subtree_preserves_tags_and_other_memberships() -> None:
    async def check() -> None:
        engine = create_async_engine(os.environ["ANALYSIS_TEST_DATABASE_URL"])
        factory = async_sessionmaker(engine, expire_on_commit=False)
        marker = uuid4().hex
        released, shared = f"released-{marker[:12]}", f"shared-{marker[:12]}"
        try:
            async with factory() as session:
                registry = TopicRegistry(session)
                await registry.ensure_topics(
                    [
                        Topic(id=released, name=f"미분류 {marker}"),
                        Topic(id=shared, name=f"공유 {marker}"),
                    ]
                )
                repository = TagFolderRepository(session)
                root = await repository.save_folder(FolderCreate(name=f"상위 {marker}"))
                child = await repository.save_folder(
                    FolderCreate(name=f"하위 {marker}", parent_id=root.id)
                )
                leaf = await repository.save_folder(
                    FolderCreate(name=f"내부 {marker}", parent_id=child.id)
                )
                other = await repository.save_folder(FolderCreate(name=f"별도 {marker}"))
                await repository.attach_tags(child.id, FolderTagAttach(tag_ids=[released, shared]))
                await repository.attach_tags(leaf.id, FolderTagAttach(tag_ids=[released]))
                await repository.attach_tags(other.id, FolderTagAttach(tag_ids=[shared]))
                with pytest.raises(TagFolderConflictError):
                    await repository.delete_folder(root.id, root.version + 1)
                await repository.delete_folder(root.id, root.version)
                remaining = {folder.id for folder in await repository.folders(FolderQuery())}
                assert {root.id, child.id, leaf.id}.isdisjoint(remaining)
                assert other.id in remaining
                unfiled = await repository.unfiled_tag_ids()
                assert released in unfiled
                assert shared not in unfiled
                assert await repository.folder_tag_ids(other.id) == {shared}
                await session.rollback()
                assert {released, shared} <= {topic.id for topic in await registry.topics()}
        finally:
            await engine.dispose()

    asyncio.run(check())
