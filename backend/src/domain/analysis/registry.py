# ruff: noqa: E501
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import and_, delete, exists, func, literal, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from domain.analysis.membership import tagged_materials
from domain.analysis.registry_models import (
    AnalysisAttemptInfo,
    AnalysisRunInfo,
    ArticleTopicOverride,
    CanonicalArticleTopicLink,
    Topic,
    TopicInfo,
    TopicMerge,
    TopicUpdate,
    normalize_label,
)
from domain.analysis.tables import (
    analysis_attempts,
    analysis_runs,
    article_sentiment_history,
    article_sentiments,
    article_topic_history,
    material_tags,
    topic_history,
    topic_labels,
)
from domain.analysis.tables import topics as analysis_topics_table
from domain.article_workflow.tables import article_inclusions, article_target_links
from domain.collection.tables import article_contents, materials
from domain.tag_folders.repository import TagFolderRepository
from domain.tag_folders.tables import folder_tags


class TopicRegistryError(RuntimeError):
    pass


class TopicRegistryNotFoundError(TopicRegistryError):
    pass


class TopicRegistryConflictError(TopicRegistryError):
    pass


class TopicRegistryInvalidMaterialError(TopicRegistryError):
    pass


class TopicRegistry:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @asynccontextmanager
    async def _transaction(self) -> AsyncGenerator[None]:
        try:
            async with self._session.begin():
                yield
        except SQLAlchemyError as error:
            raise TopicRegistryError("분석 주제 저장소 연결 실패") from error

    async def _require_news(self, material_id: UUID) -> None:
        result = await self._session.execute(
            select(materials.c.kind).where(materials.c.id == material_id)
        )
        kind = result.scalar_one_or_none()
        if kind is None:
            raise TopicRegistryNotFoundError("기사 없음")
        if kind != "news":
            raise TopicRegistryInvalidMaterialError("뉴스 기사에만 적용 가능")

    async def topics(self) -> list[TopicInfo]:
        async with self._transaction():
            statement = (
                select(analysis_topics_table)
                .where(
                    analysis_topics_table.c.merged_into.is_(None),
                    analysis_topics_table.c.archived_at.is_(None),
                )
                .order_by(analysis_topics_table.c.name)
            )
            rows = (await self._session.execute(statement)).mappings().all()
            return [TopicInfo.model_validate(row) for row in rows]

    async def folder_topic_ids(self, folder_id: UUID, include_descendants: bool = True) -> set[str]:
        async with self._transaction():
            return await TagFolderRepository(self._session).folder_tag_ids(
                folder_id, include_descendants
            )

    async def ensure_topics(self, topics: list[Topic]) -> list[TopicInfo]:
        """초기 표준 주제만 등록하고 기존 사람 수정 내용은 보존."""
        async with self._transaction():
            for topic in topics:
                statement = (
                    insert(analysis_topics_table)
                    .values(**topic.model_dump())
                    .on_conflict_do_nothing(index_elements=[analysis_topics_table.c.id])
                    .returning(analysis_topics_table.c.id)
                )
                inserted = (await self._session.execute(statement)).mappings().all()
                if not inserted:
                    continue
                for label, canonical in [
                    (topic.name, True),
                    *((item, False) for item in topic.synonyms),
                ]:
                    await self._session.execute(
                        insert(topic_labels)
                        .values(
                            id=topic.id,
                            normalized_name=normalize_label(label),
                            is_canonical=canonical,
                        )
                        .on_conflict_do_nothing(index_elements=[topic_labels.c.normalized_name])
                    )
            rows = (
                (
                    await self._session.execute(
                        select(analysis_topics_table)
                        .where(
                            analysis_topics_table.c.merged_into.is_(None),
                            analysis_topics_table.c.archived_at.is_(None),
                        )
                        .order_by(analysis_topics_table.c.name)
                    )
                )
                .mappings()
                .all()
            )
            return [TopicInfo.model_validate(row) for row in rows]

    async def archived_labels(self) -> list[str]:
        async with self._transaction():
            statement = (
                select(topic_labels.c.normalized_name)
                .join(analysis_topics_table, analysis_topics_table.c.id == topic_labels.c.id)
                .where(analysis_topics_table.c.archived_at.is_not(None))
                .order_by(topic_labels.c.normalized_name)
            )
            rows = (await self._session.execute(statement)).mappings().all()
            return [row["normalized_name"] for row in rows]

    async def run(self, run_id: UUID) -> AnalysisRunInfo:
        async with self._transaction():
            rows = (
                (
                    await self._session.execute(
                        select(analysis_runs).where(analysis_runs.c.id == run_id)
                    )
                )
                .mappings()
                .all()
            )
            if not rows:
                raise TopicRegistryNotFoundError("분석 실행 없음")
            return AnalysisRunInfo.model_validate(rows[0])

    async def runs_for_article(self, source: str, source_id: str) -> list[AnalysisRunInfo]:
        async with self._transaction():
            statement = (
                select(analysis_runs)
                .where(
                    and_(analysis_runs.c.source == source, analysis_runs.c.source_id == source_id)
                )
                .order_by(analysis_runs.c.created_at.desc(), analysis_runs.c.id.desc())
                .limit(100)
            )
            rows = (await self._session.execute(statement)).mappings().all()
            return [AnalysisRunInfo.model_validate(row) for row in rows]

    async def runs_for_canonical(self, article_id: UUID) -> list[AnalysisRunInfo]:
        async with self._transaction():
            await self._require_news(article_id)
            statement = (
                select(analysis_runs)
                .where(analysis_runs.c.article_id == article_id)
                .order_by(analysis_runs.c.created_at.desc(), analysis_runs.c.id.desc())
            )
            rows = (await self._session.execute(statement)).mappings().all()
            return [AnalysisRunInfo.model_validate(row) for row in rows]

    async def report_articles(
        self,
        article_ids: list[UUID] | None,
        target_id: UUID | None,
        folder_id: UUID | None = None,
        include_descendants: bool = True,
    ) -> list[dict]:
        async with self._transaction():
            content = (
                select(article_contents.c.content_hash, article_contents.c.body)
                .where(article_contents.c.article_id == materials.c.id)
                .order_by(article_contents.c.created_at.desc(), article_contents.c.id.desc())
                .limit(1)
                .lateral("content")
            )
            applied = (
                select(analysis_runs.c.applied_result)
                .where(
                    analysis_runs.c.article_id == materials.c.id,
                    analysis_runs.c.content_hash == content.c.content_hash,
                    analysis_runs.c.status == "completed",
                    analysis_runs.c.applied_result.is_not(None),
                )
                .order_by(analysis_runs.c.updated_at.desc(), analysis_runs.c.id.desc())
                .limit(1)
                .lateral("applied")
            )
            if folder_id is not None:
                tag_ids = await TagFolderRepository(self._session).folder_tag_ids(
                    folder_id, include_descendants
                )
                selection = tagged_materials(set(tag_ids), kind="news")
            elif article_ids is not None:
                selection = materials.c.id.in_(article_ids)
            else:
                selection = exists(
                    select(article_target_links.c.article_id).where(
                        article_target_links.c.article_id == materials.c.id,
                        article_target_links.c.target_id == target_id,
                        article_target_links.c.decision == "include",
                    )
                )
            inclusion_scope = (
                []
                if folder_id is not None
                else [func.coalesce(article_inclusions.c.decision, "include") == "include"]
            )
            statement = (
                select(
                    materials.c.id,
                    materials.c.title,
                    materials.c.publisher,
                    materials.c.summary,
                    content.c.content_hash,
                    content.c.body,
                    applied.c.applied_result,
                    article_sentiments.c.sentiment,
                    article_sentiments.c.mixed_sentiment,
                    article_sentiments.c.sentiment_reason,
                )
                .outerjoin(article_inclusions, article_inclusions.c.article_id == materials.c.id)
                .outerjoin(content, literal(True))
                .outerjoin(applied, literal(True))
                .outerjoin(article_sentiments, article_sentiments.c.article_id == materials.c.id)
                .where(
                    materials.c.kind == "news",
                    *inclusion_scope,
                    selection,
                )
                .order_by(
                    materials.c.published_at.desc().nulls_last(),
                    materials.c.created_at.desc(),
                    materials.c.id,
                )
            )
            rows = (await self._session.execute(statement)).mappings().all()
            return [dict(row) for row in rows]

    async def canonical_topic_names(self, article_id: UUID) -> list[str]:
        async with self._transaction():
            await self._require_news(article_id)
            statement = (
                select(analysis_topics_table.c.name, material_tags.c.origin)
                .join(analysis_topics_table, analysis_topics_table.c.id == material_tags.c.topic_id)
                .where(
                    material_tags.c.material_id == article_id,
                    analysis_topics_table.c.merged_into.is_(None),
                    analysis_topics_table.c.archived_at.is_(None),
                )
                .order_by(analysis_topics_table.c.name)
            )
            rows = (await self._session.execute(statement)).mappings().all()
            return [row["name"] for row in rows if row["origin"] != "manual_exclude"]

    async def attempts(self, run_id: UUID) -> list[AnalysisAttemptInfo]:
        async with self._transaction():
            rows = (
                (
                    await self._session.execute(
                        select(analysis_attempts)
                        .where(analysis_attempts.c.run_id == run_id)
                        .order_by(analysis_attempts.c.id)
                    )
                )
                .mappings()
                .all()
            )
            return [AnalysisAttemptInfo.model_validate(row) for row in rows]

    async def article_content(self, source: str, source_id: str, content_hash: str) -> dict | None:
        async with self._transaction():
            statement = (
                select(
                    article_contents.c.title,
                    article_contents.c.body,
                    func.coalesce(materials.c.publisher, article_contents.c.source).label(
                        "publisher"
                    ),
                )
                .outerjoin(materials, materials.c.id == article_contents.c.material_id)
                .where(
                    article_contents.c.source == source,
                    article_contents.c.source_id == source_id,
                    article_contents.c.content_hash == content_hash,
                )
                .limit(1)
            )
            rows = (await self._session.execute(statement)).mappings().all()
            return dict(rows[0]) if rows else None

    async def resolve_topic_id(self, topic_id: str) -> str | None:
        async with self._transaction():
            current = topic_id
            for _ in range(20):
                rows = (
                    (
                        await self._session.execute(
                            select(
                                analysis_topics_table.c.merged_into,
                                analysis_topics_table.c.archived_at,
                            ).where(analysis_topics_table.c.id == current)
                        )
                    )
                    .mappings()
                    .all()
                )
                if not rows:
                    return None
                if rows[0]["archived_at"] is not None:
                    return None
                if rows[0]["merged_into"] is None:
                    return current
                current = rows[0]["merged_into"]
            raise TopicRegistryConflictError("주제 병합 순환")

    async def save_application(self, run_id: UUID, applied: dict) -> None:
        async with self._transaction():
            statement = (
                update(analysis_runs)
                .where(analysis_runs.c.id == run_id, analysis_runs.c.status == "completed")
                .values(applied_result=applied, updated_at=func.now())
                .returning(analysis_runs.c.id)
            )
            rows = (await self._session.execute(statement)).mappings().all()
            if not rows:
                raise TopicRegistryNotFoundError("완료된 분석 실행 없음")

    async def ensure_ai_tag(self, name: str) -> str | None:
        normalized = normalize_label(name)
        async with self._transaction():
            existing = (
                (
                    await self._session.execute(
                        select(topic_labels.c.id, analysis_topics_table.c.archived_at)
                        .join(
                            analysis_topics_table, analysis_topics_table.c.id == topic_labels.c.id
                        )
                        .where(topic_labels.c.normalized_name == normalized)
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                return existing["id"] if existing["archived_at"] is None else None
            tag_id = "topic-" + uuid5(NAMESPACE_URL, f"gyeonggi-topic-id:{normalized}").hex[:12]
            await self._session.execute(
                insert(analysis_topics_table)
                .values(id=tag_id, name=name.strip(), description="", synonyms=[])
                .on_conflict_do_nothing(index_elements=[analysis_topics_table.c.id])
            )
            await self._session.execute(
                insert(topic_labels)
                .values(id=tag_id, normalized_name=normalized, is_canonical=True)
                .on_conflict_do_nothing(index_elements=[topic_labels.c.normalized_name])
            )
            return await self._session.scalar(
                select(topic_labels.c.id).where(topic_labels.c.normalized_name == normalized)
            )

    async def update(self, topic_id: str, body: TopicUpdate) -> TopicInfo:
        async with self._transaction():
            statement = (
                update(analysis_topics_table)
                .where(
                    analysis_topics_table.c.id == topic_id,
                    analysis_topics_table.c.version == body.version,
                    analysis_topics_table.c.merged_into.is_(None),
                    analysis_topics_table.c.archived_at.is_(None),
                )
                .values(
                    name=body.name,
                    description=body.description,
                    synonyms=body.synonyms,
                    version=analysis_topics_table.c.version + 1,
                    updated_at=func.now(),
                )
                .returning(analysis_topics_table)
            )
            rows = (await self._session.execute(statement)).mappings().all()
            if not rows:
                raise TopicRegistryConflictError("주제 없음 또는 버전 충돌")
            await self._session.execute(delete(topic_labels).where(topic_labels.c.id == topic_id))
            for label, canonical in [
                (body.name, True),
                *((synonym, False) for synonym in body.synonyms),
            ]:
                await self._session.execute(
                    insert(topic_labels).values(
                        id=topic_id,
                        normalized_name=normalize_label(label),
                        is_canonical=canonical,
                    )
                )
            await self._session.execute(
                insert(topic_history).values(
                    topic_id=topic_id, action="update", detail=body.model_dump(mode="json")
                )
            )
            return TopicInfo.model_validate(rows[0])

    async def merge(self, topic_id: str, body: TopicMerge) -> None:
        if topic_id == body.target_id:
            raise TopicRegistryConflictError("같은 주제 병합 불가")
        async with self._transaction():
            old_links = (
                (
                    await self._session.execute(
                        select(material_tags.c.material_id, material_tags.c.origin)
                        .where(material_tags.c.topic_id == topic_id)
                        .with_for_update()
                    )
                )
                .mappings()
                .all()
            )
            target_origins = {
                row["material_id"]: row["origin"]
                for row in (
                    (
                        await self._session.execute(
                            select(material_tags.c.material_id, material_tags.c.origin)
                            .where(material_tags.c.topic_id == body.target_id)
                            .with_for_update()
                        )
                    )
                    .mappings()
                    .all()
                )
            }
            for link in old_links:
                target_origin = target_origins.get(link["material_id"])
                if {link["origin"], target_origin} == {"manual_include", "manual_exclude"}:
                    raise TopicRegistryConflictError("사람의 상충된 기사 주제 판단")
            target_exists = await self._session.scalar(
                select(analysis_topics_table.c.id).where(
                    analysis_topics_table.c.id == body.target_id,
                    analysis_topics_table.c.merged_into.is_(None),
                    analysis_topics_table.c.archived_at.is_(None),
                )
            )
            updated = await self._session.scalar(
                update(analysis_topics_table)
                .where(
                    analysis_topics_table.c.id == topic_id,
                    analysis_topics_table.c.merged_into.is_(None),
                    analysis_topics_table.c.archived_at.is_(None),
                )
                .values(merged_into=body.target_id, updated_at=func.now())
                .returning(analysis_topics_table.c.id)
            )
            if updated is None or target_exists is None:
                raise TopicRegistryNotFoundError("병합할 주제 없음")
            await self._session.execute(
                insert(folder_tags)
                .from_select(
                    [folder_tags.c.folder_id, folder_tags.c.tag_id],
                    select(folder_tags.c.folder_id, literal(body.target_id)).where(
                        folder_tags.c.tag_id == topic_id
                    ),
                )
                .on_conflict_do_nothing(
                    index_elements=[folder_tags.c.folder_id, folder_tags.c.tag_id]
                )
            )
            for link in old_links:
                target_origin = target_origins.get(link["material_id"])
                next_origin = (
                    link["origin"]
                    if target_origin == "ai" and link["origin"] != "ai"
                    else target_origin or link["origin"]
                )
                await self._session.execute(
                    insert(material_tags)
                    .values(
                        material_id=link["material_id"],
                        topic_id=body.target_id,
                        origin=next_origin,
                    )
                    .on_conflict_do_update(
                        index_elements=[material_tags.c.material_id, material_tags.c.topic_id],
                        set_={"origin": next_origin, "updated_at": func.now()},
                    )
                )
                await self._session.execute(
                    delete(material_tags).where(
                        material_tags.c.material_id == link["material_id"],
                        material_tags.c.topic_id == topic_id,
                    )
                )
                await self._record_tag_history(
                    link["material_id"], topic_id, link["origin"], next_origin, "merge"
                )
            await self._session.execute(
                update(topic_labels).where(topic_labels.c.id == topic_id).values(id=body.target_id)
            )
            await self._session.execute(
                insert(topic_history).values(
                    topic_id=topic_id, action="merge", detail={"target_id": body.target_id}
                )
            )
            return

    async def canonical_article_topics(self, article_id: UUID) -> list[CanonicalArticleTopicLink]:
        async with self._transaction():
            await self._require_news(article_id)
            rows = (
                (
                    await self._session.execute(
                        select(material_tags.c.topic_id, material_tags.c.origin)
                        .where(material_tags.c.material_id == article_id)
                        .order_by(material_tags.c.topic_id)
                    )
                )
                .mappings()
                .all()
            )
            return [
                CanonicalArticleTopicLink(
                    article_id=article_id,
                    topic_id=row["topic_id"],
                    origin=row["origin"],
                )
                for row in rows
            ]

    async def sync_material_tags(
        self, material_id: UUID, tag_ids: list[str]
    ) -> list[CanonicalArticleTopicLink]:
        if len(tag_ids) != len(set(tag_ids)):
            raise TopicRegistryConflictError("태그 중복")
        async with self._transaction():
            await self._require_news(material_id)
            existing = (
                (
                    await self._session.execute(
                        select(material_tags.c.topic_id, material_tags.c.origin)
                        .where(material_tags.c.material_id == material_id)
                        .with_for_update()
                    )
                )
                .mappings()
                .all()
            )
            manual = {row["topic_id"] for row in existing if row["origin"] != "ai"}
            await self._session.execute(
                delete(material_tags).where(
                    material_tags.c.material_id == material_id,
                    material_tags.c.origin == "ai",
                    material_tags.c.topic_id.not_in(tag_ids or ["__none__"]),
                )
            )
            for tag_id in set(tag_ids) - manual:
                active = await self._session.scalar(
                    select(analysis_topics_table.c.id).where(
                        analysis_topics_table.c.id == tag_id,
                        analysis_topics_table.c.merged_into.is_(None),
                        analysis_topics_table.c.archived_at.is_(None),
                    )
                )
                if active is not None:
                    await self._session.execute(
                        insert(material_tags)
                        .values(material_id=material_id, topic_id=tag_id, origin="ai")
                        .on_conflict_do_nothing(
                            index_elements=[material_tags.c.material_id, material_tags.c.topic_id]
                        )
                    )
            rows = (
                (
                    await self._session.execute(
                        select(material_tags.c.topic_id, material_tags.c.origin)
                        .where(material_tags.c.material_id == material_id)
                        .order_by(material_tags.c.topic_id)
                    )
                )
                .mappings()
                .all()
            )
            return [
                CanonicalArticleTopicLink(
                    article_id=material_id, topic_id=row["topic_id"], origin=row["origin"]
                )
                for row in rows
            ]

    async def save_ai_sentiment(
        self,
        material_id: UUID,
        run_id: UUID,
        sentiment: str,
        mixed_sentiment: bool,
        sentiment_reason: str,
    ) -> None:
        async with self._transaction():
            await self._require_news(material_id)
            current = await self._session.scalar(
                select(article_sentiments.c.origin).where(
                    article_sentiments.c.article_id == material_id
                )
            )
            if current == "manual":
                return
            statement = insert(article_sentiments).values(
                article_id=material_id,
                sentiment=sentiment,
                mixed_sentiment=mixed_sentiment,
                sentiment_reason=sentiment_reason,
                origin="ai",
                run_id=run_id,
            )
            await self._session.execute(
                statement.on_conflict_do_update(
                    index_elements=[article_sentiments.c.article_id],
                    set_={
                        "sentiment": statement.excluded.sentiment,
                        "mixed_sentiment": statement.excluded.mixed_sentiment,
                        "sentiment_reason": statement.excluded.sentiment_reason,
                        "origin": "ai",
                        "run_id": statement.excluded.run_id,
                        "updated_at": func.now(),
                    },
                )
            )
            await self._session.execute(
                insert(article_sentiment_history).values(
                    article_id=material_id,
                    sentiment=sentiment,
                    mixed_sentiment=mixed_sentiment,
                    sentiment_reason=sentiment_reason,
                    origin="ai",
                    run_id=run_id,
                )
            )

    async def _record_tag_history(
        self,
        material_id: UUID,
        topic_id: str,
        previous: str | None,
        current: str | None,
        action: str = "override",
    ) -> None:
        await self._session.execute(
            insert(article_topic_history).values(
                article_id=material_id,
                original_topic_id=topic_id,
                resulting_topic_id=topic_id,
                previous_origin=previous,
                resulting_origin=current,
                action="release" if current is None else action,
            )
        )

    async def override_canonical_article_topic(
        self, article_id: UUID, topic_id: str, body: ArticleTopicOverride
    ) -> None:
        async with self._transaction():
            await self._require_news(article_id)
            topic = (
                (
                    await self._session.execute(
                        select(analysis_topics_table.c.id).where(
                            analysis_topics_table.c.id == topic_id,
                            analysis_topics_table.c.merged_into.is_(None),
                            analysis_topics_table.c.archived_at.is_(None),
                        )
                    )
                )
                .mappings()
                .all()
            )
            if not topic:
                raise TopicRegistryNotFoundError("주제 없음")
            previous = await self._session.scalar(
                select(material_tags.c.origin).where(
                    material_tags.c.material_id == article_id,
                    material_tags.c.topic_id == topic_id,
                )
            )
            if body.decision == "release":
                await self._session.execute(
                    delete(material_tags).where(
                        material_tags.c.material_id == article_id,
                        material_tags.c.topic_id == topic_id,
                        material_tags.c.origin.in_(("manual_include", "manual_exclude")),
                    )
                )
                origin = None
            else:
                origin = "manual_" + body.decision
                statement = insert(material_tags).values(
                    material_id=article_id, topic_id=topic_id, origin=origin
                )
                await self._session.execute(
                    statement.on_conflict_do_update(
                        index_elements=[material_tags.c.material_id, material_tags.c.topic_id],
                        set_={"origin": statement.excluded.origin, "updated_at": func.now()},
                    )
                )
            if previous != origin:
                await self._record_tag_history(article_id, topic_id, previous, origin)

    async def archive(self, topic_id: str) -> None:
        async with self._transaction():
            rows = (
                (
                    await self._session.execute(
                        update(analysis_topics_table)
                        .where(
                            analysis_topics_table.c.id == topic_id,
                            analysis_topics_table.c.merged_into.is_(None),
                            analysis_topics_table.c.archived_at.is_(None),
                        )
                        .values(archived_at=func.now(), updated_at=func.now())
                        .returning(analysis_topics_table.c.id)
                    )
                )
                .mappings()
                .all()
            )
            if not rows:
                raise TopicRegistryNotFoundError("보관할 주제 없음")
            await self._session.execute(
                insert(topic_history).values(topic_id=topic_id, action="archive", detail={})
            )
