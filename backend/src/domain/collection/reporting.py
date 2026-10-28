from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, Date, and_, case, cast, func, literal, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from domain.analysis.membership import tagged_materials
from domain.article_workflow.tables import (
    article_inclusions,
    article_sentiments,
    article_target_links,
)
from domain.collection.errors import (
    CollectionInvalidMaterialError,
    CollectionNotFoundError,
    CollectionUnavailableError,
)
from domain.collection.models import (
    ArticleQuery,
    MaterialQuery,
    Overview,
    StoredArticle,
    StoredArticleDetail,
    StoredArticlePage,
    StoredMaterial,
    StoredMaterialDetail,
    StoredMaterialPage,
)
from domain.collection.tables import (
    article_contents,
    article_detail_results,
    article_detail_runs,
    collection_requests,
    collection_rules,
    material_sources,
    materials,
)
from domain.tag_folders.repository import TagFolderRepository


class CollectionReporting:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def rows(self, statement) -> list[dict]:
        try:
            result = await self._session.execute(statement)
            return [dict(row) for row in result.mappings().all()]
        except SQLAlchemyError as error:
            raise CollectionUnavailableError("수집 결과 저장소 연결 실패") from error

    def material_query(self, include_review: bool = False):
        latest = (
            select(
                article_contents.c.body,
                article_contents.c.content_hash,
                article_contents.c.created_at,
                article_contents.c.original_published_on,
                article_contents.c.original_published_at,
                article_contents.c.original_modified_on,
                article_contents.c.original_modified_at,
            )
            .where(article_contents.c.article_id == materials.c.id)
            .order_by(article_contents.c.created_at.desc(), article_contents.c.id.desc())
            .limit(1)
            .lateral("latest_content")
        )
        detail = (
            select(
                article_detail_results.c.result["status"].astext.label("status"),
                article_detail_results.c.result["skip_reason"].astext.label("skip_reason"),
            )
            .select_from(
                article_detail_results.join(
                    article_detail_runs,
                    article_detail_runs.c.id == article_detail_results.c.run_id,
                ).join(
                    material_sources,
                    and_(
                        material_sources.c.source_id == article_detail_results.c.source_id,
                        material_sources.c.source
                        == article_detail_results.c.result["seed"]["source"].astext,
                    ),
                )
            )
            .where(
                material_sources.c.material_id == materials.c.id,
                material_sources.c.source.in_(("bigkinds", "naver_news")),
            )
            .order_by(
                article_detail_runs.c.summary["started_at"].astext.desc(),
                article_detail_runs.c.id.desc(),
            )
            .limit(1)
            .correlate(materials)
            .lateral("latest_detail")
        )
        source = (
            materials.outerjoin(latest, literal(True))
            .outerjoin(detail, literal(True))
            .outerjoin(article_sentiments, article_sentiments.c.article_id == materials.c.id)
        )
        fields = [
            materials.c.id,
            materials.c.kind,
            materials.c.title,
            func.coalesce(materials.c.summary, "").label("summary"),
            materials.c.publisher,
            materials.c.blog_name,
            materials.c.blog_url,
            materials.c.published_on,
            materials.c.published_at,
            materials.c.updated_at,
            func.coalesce(func.substr(latest.c.body, 1, 240), "").label("content_preview"),
            latest.c.body.is_not(None).label("has_body"),
            case(
                (and_(latest.c.body.is_(None), detail.c.status == "skipped"), detail.c.skip_reason),
                else_=None,
            ).label("body_skip_reason"),
            latest.c.body,
            latest.c.content_hash,
            latest.c.created_at.label("body_collected_at"),
            latest.c.original_published_on,
            latest.c.original_published_at,
            latest.c.original_modified_on,
            latest.c.original_modified_at,
            article_sentiments.c.sentiment,
            article_sentiments.c.mixed_sentiment,
            article_sentiments.c.sentiment_reason,
            article_sentiments.c.origin.label("sentiment_origin"),
        ]
        if include_review:
            source = source.outerjoin(
                article_inclusions, article_inclusions.c.article_id == materials.c.id
            )
            fields.extend(
                [
                    func.coalesce(article_inclusions.c.decision, "include").label("inclusion"),
                    article_inclusions.c.reason.label("inclusion_reason"),
                ]
            )
        return select(*fields).select_from(source).where(materials.c.kind.in_(("news", "blog")))

    async def sources(self, material_ids: list[UUID]) -> dict[UUID, list[dict]]:
        result: dict[UUID, list[dict]] = {material_id: [] for material_id in material_ids}
        if material_ids:
            rows = await self.rows(
                select(material_sources)
                .where(material_sources.c.material_id.in_(material_ids))
                .order_by(
                    material_sources.c.first_seen_at,
                    material_sources.c.source,
                    material_sources.c.source_id,
                )
            )
            for row in rows:
                result[row["material_id"]].append(row)
        return result

    async def article(self, article_id: UUID) -> StoredArticleDetail:
        rows = await self.rows(
            self.material_query(include_review=True).where(
                materials.c.id == article_id, materials.c.kind == "news"
            )
        )
        if not rows:
            exists = await self.rows(select(materials.c.kind).where(materials.c.id == article_id))
            if exists and exists[0]["kind"] != "news":
                raise CollectionInvalidMaterialError("뉴스 기사에만 적용 가능")
            raise CollectionNotFoundError(
                "저장된 자료가 없어요. 수집 자료 목록에서 다시 선택해 주세요."
            )
        source_map = await self.sources([article_id])
        return StoredArticleDetail.model_validate({**rows[0], "sources": source_map[article_id]})

    async def material(self, material_id: UUID) -> StoredMaterialDetail:
        rows = await self.rows(self.material_query().where(materials.c.id == material_id))
        if not rows:
            raise CollectionNotFoundError("저장된 자료 없음")
        source_map = await self.sources([material_id])
        return StoredMaterialDetail.model_validate({**rows[0], "sources": source_map[material_id]})

    async def materials(self, query: MaterialQuery) -> StoredMaterialPage:
        criteria: list[ColumnElement[bool]] = [materials.c.kind.in_(("news", "blog"))]
        if query.kind is not None:
            criteria.append(materials.c.kind == query.kind)
        elif query.group == "news":
            criteria.append(materials.c.kind == "news")
        elif query.group == "posts":
            criteria.append(materials.c.kind == "blog")
        if query.source is not None:
            criteria.append(
                select(material_sources.c.source_id)
                .where(
                    material_sources.c.material_id == materials.c.id,
                    material_sources.c.source == query.source,
                )
                .exists()
            )
        if query.q:
            escaped = query.q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            criteria.append(
                or_(
                    materials.c.title.ilike(pattern, escape="\\"),
                    materials.c.summary.ilike(pattern, escape="\\"),
                )
            )
        if query.tag_id is not None:
            criteria.append(tagged_materials({query.tag_id}))
        if query.folder_id is not None:
            tag_ids = await TagFolderRepository(self._session).folder_tag_ids(
                query.folder_id, query.include_descendants
            )
            criteria.append(tagged_materials(tag_ids))
        if query.unfiled:
            tag_ids = await TagFolderRepository(self._session).unfiled_tag_ids()
            criteria.append(tagged_materials(tag_ids))
        total = (
            await self.rows(
                select(func.count().label("count")).select_from(materials).where(*criteria)
            )
        )[0]["count"]
        rows = await self.rows(
            self.material_query()
            .where(*criteria)
            .order_by(materials.c.updated_at.desc(), materials.c.id)
            .limit(query.limit)
            .offset(query.offset)
        )
        source_map = await self.sources([row["id"] for row in rows])
        return StoredMaterialPage(
            items=[
                StoredMaterial.model_validate({**row, "sources": source_map[row["id"]]})
                for row in rows
            ],
            total=total,
        )

    async def overview(self) -> Overview:
        source_rows = await self.rows(
            select(material_sources.c.source, func.count().label("count"))
            .where(material_sources.c.source.in_(("bigkinds", "naver_news", "naver_blog")))
            .group_by(material_sources.c.source)
        )
        threshold = datetime.now(UTC) - timedelta(days=1)
        counts = (
            await self.rows(
                select(
                    func.count()
                    .filter(
                        collection_requests.c.status.in_(
                            ("queued", "submitted", "running", "cancelling")
                        )
                    )
                    .label("queued_requests"),
                    func.count()
                    .filter(
                        collection_requests.c.status == "failed",
                        collection_requests.c.updated_at >= threshold,
                    )
                    .label("failed_requests"),
                    func.count()
                    .filter(
                        collection_requests.c.status == "partial",
                        collection_requests.c.updated_at >= threshold,
                    )
                    .label("partial_requests"),
                )
            )
        )[0]
        rule_counts = (
            await self.rows(
                select(
                    func.count().label("total_rules"),
                    func.count()
                    .filter(collection_rules.c.definition["enabled"].astext == "true")
                    .label("active_rules"),
                )
            )
        )[0]
        today = datetime.now(ZoneInfo("Asia/Seoul")).date()
        first_day = today - timedelta(days=6)
        day = cast(func.timezone("Asia/Seoul", materials.c.created_at), Date).label("day")
        daily_rows = await self.rows(
            select(day, func.count().label("count"))
            .where(
                materials.c.created_at >= datetime.now(UTC) - timedelta(days=7),
                materials.c.kind.in_(("news", "blog")),
            )
            .group_by(day)
        )
        daily = {row["day"]: row["count"] for row in daily_rows}
        total = (
            await self.rows(
                select(func.count().label("count"))
                .select_from(materials)
                .where(materials.c.kind.in_(("news", "blog")))
            )
        )[0]
        kinds = await self.rows(
            select(materials.c.kind, func.count().label("count"))
            .where(materials.c.kind.in_(("news", "blog")))
            .group_by(materials.c.kind)
        )
        body_status = self.material_query().subquery()
        skipped = (
            await self.rows(
                select(func.count().label("count"))
                .select_from(body_status)
                .where(body_status.c.kind == "news", body_status.c.body_skip_reason.is_not(None))
            )
        )[0]["count"]
        return Overview.model_validate(
            {
                **counts,
                **rule_counts,
                "total_items": total["count"],
                "kind_counts": {
                    "news": next((row["count"] for row in kinds if row["kind"] == "news"), 0),
                    "blog": next((row["count"] for row in kinds if row["kind"] == "blog"), 0),
                },
                "source_counts": {row["source"]: row["count"] for row in source_rows},
                "body_skipped_articles": skipped,
                "daily_counts": [
                    {
                        "day": first_day + timedelta(days=offset),
                        "count": daily.get(first_day + timedelta(days=offset), 0),
                    }
                    for offset in range(7)
                ],
            }
        )

    async def articles(self, query: ArticleQuery) -> StoredArticlePage:
        criteria = []
        criteria.append(materials.c.kind == "news")
        if query.source is not None:
            criteria.append(
                select(material_sources.c.source_id)
                .where(
                    material_sources.c.material_id == materials.c.id,
                    material_sources.c.source == query.source,
                )
                .exists()
            )
        if query.q:
            escaped = query.q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            criteria.append(
                or_(
                    materials.c.title.ilike(pattern, escape="\\"),
                    materials.c.summary.ilike(pattern, escape="\\"),
                )
            )
        inclusion = func.coalesce(article_inclusions.c.decision, "include")
        if query.inclusion == "included":
            criteria.append(inclusion == "include")
        elif query.inclusion == "excluded":
            criteria.append(inclusion == "exclude")
        if query.target_id is not None:
            criteria.append(
                select(article_target_links.c.article_id)
                .where(
                    article_target_links.c.article_id == materials.c.id,
                    article_target_links.c.target_id == query.target_id,
                    article_target_links.c.decision == "include",
                )
                .exists()
            )
        if query.tag_id is not None:
            criteria.append(tagged_materials({query.tag_id}, kind="news"))
        if query.folder_id is not None:
            tag_ids = await TagFolderRepository(self._session).folder_tag_ids(
                query.folder_id, query.include_descendants
            )
            criteria.append(tagged_materials(set(tag_ids), kind="news"))
        if query.unfiled:
            tag_ids = await TagFolderRepository(self._session).unfiled_tag_ids()
            criteria.append(tagged_materials(tag_ids, kind="news"))
        base = materials.outerjoin(
            article_inclusions, article_inclusions.c.article_id == materials.c.id
        )
        total = (
            await self.rows(select(func.count().label("count")).select_from(base).where(*criteria))
        )[0]["count"]
        rows = await self.rows(
            self.material_query(include_review=True)
            .where(*criteria)
            .order_by(materials.c.updated_at.desc(), materials.c.id)
            .limit(query.limit)
            .offset(query.offset)
        )
        source_map = await self.sources([row["id"] for row in rows])
        return StoredArticlePage(
            items=[
                StoredArticle.model_validate({**row, "sources": source_map[row["id"]]})
                for row in rows
            ],
            total=total,
        )
