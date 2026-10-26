# ruff: noqa: E501
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import Text, and_, delete, exists, func, literal, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from domain.analysis.membership import tagged_materials
from domain.analysis.registry_models import (
    AnalysisAttemptInfo,
    AnalysisRunInfo,
    ArticleTopicLink,
    ArticleTopicOverride,
    CandidateInfo,
    CanonicalArticleTopicLink,
    RegistryEvidenceResult,
    Topic,
    TopicEvidenceCreate,
    TopicInfo,
    TopicMerge,
    TopicUpdate,
    normalize_label,
)
from domain.analysis.tables import (
    analysis_attempts,
    analysis_runs,
    article_topic_history,
    article_topics,
    article_versions,
    candidates,
    topic_history,
    topic_labels,
)
from domain.analysis.tables import (
    evidence as evidence_table,
)
from domain.analysis.tables import (
    topics as analysis_topics_table,
)
from domain.article_workflow.tables import article_inclusions, article_target_links
from domain.collection.tables import article_contents, material_sources, materials
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

    @staticmethod
    def _candidate_statement():
        article_key = func.coalesce(
            evidence_table.c.article_id.cast(Text),
            evidence_table.c.source + literal(":") + evidence_table.c.source_id,
        )
        return (
            select(
                candidates.c.id,
                candidates.c.name,
                candidates.c.description,
                func.count(func.distinct(article_key)).label("article_count"),
                func.count(func.distinct(evidence_table.c.publisher)).label("publisher_count"),
                candidates.c.promoted_topic_id,
                candidates.c.created_at,
                candidates.c.updated_at,
            )
            .outerjoin(evidence_table, evidence_table.c.candidate_id == candidates.c.id)
            .group_by(candidates.c.id)
        )

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

    async def candidates(self) -> list[CandidateInfo]:
        async with self._transaction():
            rows = (
                (
                    await self._session.execute(
                        self._candidate_statement().order_by(candidates.c.updated_at.desc())
                    )
                )
                .mappings()
                .all()
            )
            return [CandidateInfo.model_validate(row) for row in rows]

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

    async def runs_for_canonical_article(self, article_id: UUID) -> list[AnalysisRunInfo]:
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
                .where(article_contents.c.material_id == materials.c.id)
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
                )
                .outerjoin(article_inclusions, article_inclusions.c.article_id == materials.c.id)
                .outerjoin(content, literal(True))
                .outerjoin(applied, literal(True))
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
                select(
                    analysis_topics_table.c.name,
                    func.bool_or(article_topics.c.origin == "manual_include").label(
                        "manual_include"
                    ),
                    func.bool_or(article_topics.c.origin == "manual_exclude").label(
                        "manual_exclude"
                    ),
                    func.bool_or(article_topics.c.origin == "ai").label("ai_include"),
                )
                .join(
                    material_sources,
                    and_(
                        material_sources.c.source == article_topics.c.source,
                        material_sources.c.source_id == article_topics.c.source_id,
                    ),
                )
                .join(
                    analysis_topics_table, analysis_topics_table.c.id == article_topics.c.topic_id
                )
                .where(
                    material_sources.c.material_id == article_id,
                    analysis_topics_table.c.merged_into.is_(None),
                    analysis_topics_table.c.archived_at.is_(None),
                )
                .group_by(analysis_topics_table.c.id, analysis_topics_table.c.name)
                .order_by(analysis_topics_table.c.name)
            )
            rows = (await self._session.execute(statement)).mappings().all()
            if any(row["manual_include"] and row["manual_exclude"] for row in rows):
                raise TopicRegistryConflictError("수집처 간 상충된 수동 주제 판단")
            return [
                row["name"]
                for row in rows
                if row["manual_include"] or (row["ai_include"] and not row["manual_exclude"])
            ]

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

    async def record(self, evidence: TopicEvidenceCreate) -> RegistryEvidenceResult:
        normalized = normalize_label(evidence.name)
        async with self._transaction():
            statement = (
                select(topic_labels.c.id, analysis_topics_table.c.archived_at)
                .join(analysis_topics_table, analysis_topics_table.c.id == topic_labels.c.id)
                .where(topic_labels.c.normalized_name == normalized)
                .order_by(topic_labels.c.is_canonical.desc())
                .limit(1)
                .with_for_update(read=True)
            )
            matches = (await self._session.execute(statement)).mappings().all()
            if matches:
                if matches[0]["archived_at"] is not None:
                    raise TopicRegistryConflictError("보관된 주제명·별칭 재사용 불가")
                await self._insert_ai_link(evidence.source, evidence.source_id, matches[0]["id"])
                return RegistryEvidenceResult(kind="existing_topic", topic_id=matches[0]["id"])
            candidate_id = uuid5(NAMESPACE_URL, f"gyeonggi-topic:{normalized}")
            await self._session.execute(
                insert(candidates)
                .values(
                    id=candidate_id,
                    normalized_name=normalized,
                    name=evidence.name,
                    description=evidence.description,
                )
                .on_conflict_do_update(
                    index_elements=[candidates.c.normalized_name], set_={"updated_at": func.now()}
                )
            )
            article_id = (
                select(material_sources.c.material_id)
                .where(
                    material_sources.c.source == evidence.source,
                    material_sources.c.source_id == evidence.source_id,
                )
                .scalar_subquery()
            )
            await self._session.execute(
                insert(evidence_table)
                .values(
                    candidate_id=candidate_id,
                    source=evidence.source,
                    source_id=evidence.source_id,
                    article_id=article_id,
                    publisher=evidence.publisher,
                    quote=evidence.quote,
                )
                .on_conflict_do_nothing()
            )
            candidate = await self._candidate(candidate_id)
            if candidate.promoted_topic_id:
                await self._insert_ai_link(
                    evidence.source, evidence.source_id, candidate.promoted_topic_id
                )
                return RegistryEvidenceResult(
                    kind="promoted", topic_id=candidate.promoted_topic_id, candidate=candidate
                )
            topic_id = "topic-" + uuid5(NAMESPACE_URL, f"gyeonggi-topic-id:{normalized}").hex[:12]
            await self._session.execute(
                insert(analysis_topics_table)
                .values(
                    id=topic_id,
                    name=candidate.name,
                    description=candidate.description,
                    synonyms=[],
                )
                .on_conflict_do_nothing(index_elements=[analysis_topics_table.c.id])
            )
            await self._session.execute(
                insert(topic_labels)
                .values(id=topic_id, normalized_name=normalized, is_canonical=True)
                .on_conflict_do_nothing(index_elements=[topic_labels.c.normalized_name])
            )
            await self._session.execute(
                update(candidates)
                .where(candidates.c.id == candidate_id)
                .values(promoted_topic_id=topic_id)
            )
            evidence_rows = (
                (
                    await self._session.execute(
                        select(evidence_table.c.source, evidence_table.c.source_id).where(
                            evidence_table.c.candidate_id == candidate_id
                        )
                    )
                )
                .mappings()
                .all()
            )
            for row in evidence_rows:
                await self._insert_ai_link(row["source"], row["source_id"], topic_id)
            candidate = await self._candidate(candidate_id)
            return RegistryEvidenceResult(kind="promoted", topic_id=topic_id, candidate=candidate)

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

    async def _candidate(self, candidate_id: UUID) -> CandidateInfo:
        rows = (
            (
                await self._session.execute(
                    self._candidate_statement().where(candidates.c.id == candidate_id)
                )
            )
            .mappings()
            .all()
        )
        return CandidateInfo.model_validate(rows[0])

    async def _insert_ai_link(self, source: str, source_id: str, topic_id: str) -> None:
        article_id = (
            select(material_sources.c.material_id)
            .where(material_sources.c.source == source, material_sources.c.source_id == source_id)
            .scalar_subquery()
        )
        await self._session.execute(
            insert(article_topics)
            .values(
                source=source,
                source_id=source_id,
                article_id=article_id,
                topic_id=topic_id,
                origin="ai",
            )
            .on_conflict_do_nothing(
                index_elements=[
                    article_topics.c.source,
                    article_topics.c.source_id,
                    article_topics.c.topic_id,
                ]
            )
        )

    async def _canonical_topic_rows(self, article_id: UUID):
        statement = (
            select(
                article_topics.c.topic_id,
                func.bool_or(article_topics.c.origin == "manual_include").label("manual_include"),
                func.bool_or(article_topics.c.origin == "manual_exclude").label("manual_exclude"),
                func.bool_or(article_topics.c.origin == "ai").label("ai_include"),
            )
            .join(
                material_sources,
                and_(
                    material_sources.c.source == article_topics.c.source,
                    material_sources.c.source_id == article_topics.c.source_id,
                ),
            )
            .where(material_sources.c.material_id == article_id)
            .group_by(article_topics.c.topic_id)
            .order_by(article_topics.c.topic_id)
        )
        return (await self._session.execute(statement)).mappings().all()

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
            old, target = article_topics.alias("old"), article_topics.alias("target")
            old_source, target_source = (
                material_sources.alias("old_source"),
                material_sources.alias("target_source"),
            )
            same_article = or_(
                and_(old.c.source == target.c.source, old.c.source_id == target.c.source_id),
                and_(
                    old_source.c.material_id.is_not(None),
                    old_source.c.material_id == target_source.c.material_id,
                ),
            )
            conflicts = (
                (
                    await self._session.execute(
                        select(old.c.topic_id)
                        .select_from(
                            old.outerjoin(
                                old_source,
                                and_(
                                    old_source.c.source == old.c.source,
                                    old_source.c.source_id == old.c.source_id,
                                ),
                            )
                            .join(target, target.c.topic_id == body.target_id)
                            .outerjoin(
                                target_source,
                                and_(
                                    target_source.c.source == target.c.source,
                                    target_source.c.source_id == target.c.source_id,
                                ),
                            )
                        )
                        .where(
                            old.c.topic_id == topic_id,
                            same_article,
                            or_(
                                and_(
                                    old.c.origin == "manual_include",
                                    target.c.origin == "manual_exclude",
                                ),
                                and_(
                                    old.c.origin == "manual_exclude",
                                    target.c.origin == "manual_include",
                                ),
                            ),
                        )
                        .limit(1)
                    )
                )
                .mappings()
                .all()
            )
            if conflicts:
                raise TopicRegistryConflictError("사람의 상충된 기사 주제 판단")
            rows = (
                (
                    await self._session.execute(
                        update(analysis_topics_table)
                        .where(
                            analysis_topics_table.c.id == topic_id,
                            analysis_topics_table.c.merged_into.is_(None),
                            analysis_topics_table.c.archived_at.is_(None),
                        )
                        .values(merged_into=body.target_id, updated_at=func.now())
                        .returning(analysis_topics_table.c.id)
                    )
                )
                .mappings()
                .all()
            )
            target_rows = (
                (
                    await self._session.execute(
                        select(analysis_topics_table.c.id).where(
                            analysis_topics_table.c.id == body.target_id,
                            analysis_topics_table.c.merged_into.is_(None),
                            analysis_topics_table.c.archived_at.is_(None),
                        )
                    )
                )
                .mappings()
                .all()
            )
            if not rows or not target_rows:
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
            links = (
                (
                    await self._session.execute(
                        select(
                            article_topics.c.source,
                            article_topics.c.source_id,
                            article_topics.c.origin,
                        ).where(article_topics.c.topic_id == topic_id)
                    )
                )
                .mappings()
                .all()
            )
            for link in links:
                target_link = (
                    (
                        await self._session.execute(
                            select(article_topics.c.origin).where(
                                article_topics.c.source == link["source"],
                                article_topics.c.source_id == link["source_id"],
                                article_topics.c.topic_id == body.target_id,
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
                if target_link:
                    if (
                        link["origin"] in {"manual_include", "manual_exclude"}
                        and target_link[0]["origin"] == "ai"
                    ):
                        await self._session.execute(
                            update(article_topics)
                            .where(
                                article_topics.c.source == link["source"],
                                article_topics.c.source_id == link["source_id"],
                                article_topics.c.topic_id == body.target_id,
                            )
                            .values(origin=link["origin"], updated_at=func.now())
                        )
                    await self._session.execute(
                        delete(article_topics).where(
                            article_topics.c.source == link["source"],
                            article_topics.c.source_id == link["source_id"],
                            article_topics.c.topic_id == topic_id,
                        )
                    )
                else:
                    await self._session.execute(
                        update(article_topics)
                        .where(
                            article_topics.c.source == link["source"],
                            article_topics.c.source_id == link["source_id"],
                            article_topics.c.topic_id == topic_id,
                        )
                        .values(topic_id=body.target_id, updated_at=func.now())
                    )
            for link in links:
                await self._link_history(
                    link["source"],
                    link["source_id"],
                    topic_id,
                    body.target_id,
                    link["origin"],
                    link["origin"],
                    "merge",
                )
            await self._session.execute(
                update(topic_labels).where(topic_labels.c.id == topic_id).values(id=body.target_id)
            )
            await self._session.execute(
                insert(topic_history).values(
                    topic_id=topic_id, action="merge", detail={"target_id": body.target_id}
                )
            )

    async def sync_article_topics(
        self, source: str, source_id: str, topic_ids: list[str], content_hash: str | None = None
    ) -> list[ArticleTopicLink]:
        """AI 연결은 수동 결정을 보존하며, 이전 AI 연결만 동기화."""
        if len(topic_ids) != len(set(topic_ids)):
            raise TopicRegistryConflictError("기사 주제 중복")
        async with self._transaction():
            article_rows = (
                (
                    await self._session.execute(
                        select(material_sources.c.material_id).where(
                            material_sources.c.source == source,
                            material_sources.c.source_id == source_id,
                        )
                    )
                )
                .mappings()
                .all()
            )
            if not article_rows:
                raise TopicRegistryNotFoundError("기사 없음")
            article_id = article_rows[0]["material_id"]
            await self._require_news(article_id)
            if content_hash:
                await self._session.execute(
                    insert(article_versions)
                    .values(
                        source=source,
                        source_id=source_id,
                        article_id=article_id,
                        content_hash=content_hash,
                    )
                    .on_conflict_do_nothing()
                )
            existing = (
                (
                    await self._session.execute(
                        select(article_topics.c.topic_id, article_topics.c.origin)
                        .join(
                            material_sources,
                            and_(
                                material_sources.c.source == article_topics.c.source,
                                material_sources.c.source_id == article_topics.c.source_id,
                            ),
                        )
                        .where(material_sources.c.material_id == article_id)
                        .with_for_update(of=article_topics)
                    )
                )
                .mappings()
                .all()
            )
            manual = {row["topic_id"] for row in existing if row["origin"] != "ai"}
            if any(
                {row["origin"] for row in existing if row["topic_id"] == topic_id}
                >= {"manual_include", "manual_exclude"}
                for topic_id in manual
            ):
                raise TopicRegistryConflictError("수집처 간 상충된 수동 주제 판단")
            source_match = exists(
                select(material_sources.c.source).where(
                    material_sources.c.source == article_topics.c.source,
                    material_sources.c.source_id == article_topics.c.source_id,
                    material_sources.c.material_id == article_id,
                )
            )
            await self._session.execute(
                delete(article_topics).where(
                    article_topics.c.origin == "ai",
                    source_match,
                    article_topics.c.topic_id.not_in(topic_ids or ["__none__"]),
                )
            )
            for topic_id in set(topic_ids) - manual:
                available = (
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
                if not available:
                    continue
                source_rows = (
                    (
                        await self._session.execute(
                            select(material_sources.c.source, material_sources.c.source_id).where(
                                material_sources.c.material_id == article_id
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
                for source_row in source_rows:
                    await self._insert_ai_link(
                        source_row["source"], source_row["source_id"], topic_id
                    )
            rows = await self._canonical_topic_rows(article_id)
            return [
                ArticleTopicLink(
                    source=source,
                    source_id=source_id,
                    topic_id=row["topic_id"],
                    origin=(
                        "manual_exclude"
                        if row["manual_exclude"]
                        else "manual_include"
                        if row["manual_include"]
                        else "ai"
                    ),
                )
                for row in rows
            ]

    async def article_topics(self, source: str, source_id: str) -> list[ArticleTopicLink]:
        async with self._transaction():
            rows = (
                (
                    await self._session.execute(
                        select(
                            article_topics.c.source,
                            article_topics.c.source_id,
                            article_topics.c.topic_id,
                            article_topics.c.origin,
                        )
                        .where(
                            article_topics.c.source == source,
                            article_topics.c.source_id == source_id,
                        )
                        .order_by(article_topics.c.topic_id)
                    )
                )
                .mappings()
                .all()
            )
            return [ArticleTopicLink.model_validate(row) for row in rows]

    async def canonical_article_topics(self, article_id: UUID) -> list[CanonicalArticleTopicLink]:
        async with self._transaction():
            await self._require_news(article_id)
            rows = await self._canonical_topic_rows(article_id)
            return [
                CanonicalArticleTopicLink(
                    article_id=article_id,
                    topic_id=row["topic_id"],
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

    async def override_canonical_article_topic(
        self, article_id: UUID, topic_id: str, body: ArticleTopicOverride
    ) -> None:
        async with self._transaction():
            await self._require_news(article_id)
            source_rows = (
                (
                    await self._session.execute(
                        select(material_sources.c.source, material_sources.c.source_id)
                        .where(material_sources.c.material_id == article_id)
                        .order_by(material_sources.c.source, material_sources.c.source_id)
                    )
                )
                .mappings()
                .all()
            )
            if not source_rows:
                raise TopicRegistryNotFoundError("기사 없음")
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
            for source in source_rows:
                previous = (
                    (
                        await self._session.execute(
                            select(article_topics.c.origin).where(
                                article_topics.c.topic_id == topic_id,
                                article_topics.c.source == source["source"],
                                article_topics.c.source_id == source["source_id"],
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
                prior = previous[0]["origin"] if previous else None
                if body.decision == "release":
                    await self._session.execute(
                        delete(article_topics).where(
                            article_topics.c.topic_id == topic_id,
                            article_topics.c.source == source["source"],
                            article_topics.c.source_id == source["source_id"],
                            article_topics.c.origin.in_(("manual_include", "manual_exclude")),
                        )
                    )
                    next_origin = None
                else:
                    next_origin = "manual_" + body.decision
                    statement = insert(article_topics).values(
                        source=source["source"],
                        source_id=source["source_id"],
                        article_id=article_id,
                        topic_id=topic_id,
                        origin=next_origin,
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
                if prior != next_origin:
                    await self._link_history(
                        source["source"],
                        source["source_id"],
                        topic_id,
                        topic_id,
                        prior,
                        next_origin,
                        "release" if body.decision == "release" else "override",
                    )

    async def override_article_topic(
        self, source: str, source_id: str, topic_id: str, body: ArticleTopicOverride
    ) -> None:
        async with self._transaction():
            previous = (
                (
                    await self._session.execute(
                        select(article_topics.c.origin).where(
                            article_topics.c.source == source,
                            article_topics.c.source_id == source_id,
                            article_topics.c.topic_id == topic_id,
                        )
                    )
                )
                .mappings()
                .all()
            )
            previous_origin = previous[0]["origin"] if previous else None
            if body.decision == "release":
                await self._session.execute(
                    delete(article_topics).where(
                        article_topics.c.source == source,
                        article_topics.c.source_id == source_id,
                        article_topics.c.topic_id == topic_id,
                        article_topics.c.origin.in_(("manual_include", "manual_exclude")),
                    )
                )
                await self._link_history(
                    source, source_id, topic_id, topic_id, previous_origin, None, "release"
                )
                return
            exists_topic = (
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
            if not exists_topic:
                raise TopicRegistryNotFoundError("주제 없음")
            origin = "manual_" + body.decision
            article_id = (
                select(material_sources.c.material_id)
                .where(
                    material_sources.c.source == source, material_sources.c.source_id == source_id
                )
                .scalar_subquery()
            )
            statement = insert(article_topics).values(
                source=source,
                source_id=source_id,
                article_id=article_id,
                topic_id=topic_id,
                origin=origin,
            )
            await self._session.execute(
                statement.on_conflict_do_update(
                    index_elements=[
                        article_topics.c.source,
                        article_topics.c.source_id,
                        article_topics.c.topic_id,
                    ],
                    set_={"origin": statement.excluded.origin, "updated_at": func.now()},
                )
            )
            await self._link_history(
                source, source_id, topic_id, topic_id, previous_origin, origin, "override"
            )

    async def _link_history(
        self,
        source: str,
        source_id: str,
        original: str,
        resulting: str | None,
        previous: str | None,
        current: str | None,
        action: str,
    ) -> None:
        await self._session.execute(
            insert(article_topic_history).values(
                source=source,
                source_id=source_id,
                original_topic_id=original,
                resulting_topic_id=resulting,
                previous_origin=previous,
                resulting_origin=current,
                action=action,
            )
        )

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
