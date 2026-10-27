from uuid import UUID

from sqlalchemy import case, func, insert, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from domain.article_workflow.models import ReprintInfo, SentimentInfo, SentimentWrite
from domain.article_workflow.repository import WorkflowInvalidMaterial, WorkflowNotFound
from domain.article_workflow.tables import (
    article_reprints,
    article_sentiment_history,
    article_sentiments,
)
from domain.collection.tables import article_contents, articles, materials


class ArticleRelations:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _require_article(self, article_id: UUID) -> None:
        exists = await self._session.scalar(
            select(articles.c.id).where(articles.c.id == article_id)
        )
        if exists is not None:
            return
        kind = await self._session.scalar(
            select(materials.c.kind).where(materials.c.id == article_id)
        )
        if kind is not None:
            raise WorkflowInvalidMaterial("뉴스 기사에만 적용 가능")
        raise WorkflowNotFound("기사 없음")

    async def sentiment(self, article_id: UUID) -> SentimentInfo:
        await self._require_article(article_id)
        row = (
            (
                await self._session.execute(
                    select(article_sentiments).where(article_sentiments.c.article_id == article_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return SentimentInfo(
                article_id=article_id,
                sentiment=None,
                mixed_sentiment=None,
                sentiment_reason=None,
                origin=None,
                updated_at=None,
            )
        return SentimentInfo.model_validate(dict(row))

    async def override_sentiment(self, article_id: UUID, body: SentimentWrite) -> SentimentInfo:
        await self._require_article(article_id)
        async with self._session.begin_nested():
            values = {
                "article_id": article_id,
                "sentiment": body.sentiment,
                "mixed_sentiment": body.mixed_sentiment,
                "sentiment_reason": body.sentiment_reason,
                "origin": "manual",
                "run_id": None,
            }
            await self._session.execute(
                pg_insert(article_sentiments)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=[article_sentiments.c.article_id],
                    set_={**values, "updated_at": func.now()},
                )
            )
            await self._session.execute(insert(article_sentiment_history).values(**values))
        await self._session.commit()
        return await self.sentiment(article_id)

    async def reprints(self, article_id: UUID) -> list[ReprintInfo]:
        await self._require_article(article_id)
        other_id = case(
            (article_reprints.c.article_a_id == article_id, article_reprints.c.article_b_id),
            else_=article_reprints.c.article_a_id,
        )
        current_self_hash = case(
            (
                article_reprints.c.article_a_id == article_id,
                article_reprints.c.article_a_content_hash,
            ),
            else_=article_reprints.c.article_b_content_hash,
        )
        current_other_hash = case(
            (
                article_reprints.c.article_a_id == article_id,
                article_reprints.c.article_b_content_hash,
            ),
            else_=article_reprints.c.article_a_content_hash,
        )
        other = articles.alias("other_article")
        own_hash = (
            select(article_contents.c.content_hash)
            .where(article_contents.c.article_id == article_id)
            .order_by(article_contents.c.created_at.desc(), article_contents.c.id.desc())
            .limit(1)
            .scalar_subquery()
        )
        other_hash = (
            select(article_contents.c.content_hash)
            .where(article_contents.c.article_id == other.c.id)
            .order_by(article_contents.c.created_at.desc(), article_contents.c.id.desc())
            .limit(1)
            .scalar_subquery()
        )
        rows = (
            (
                await self._session.execute(
                    select(
                        other.c.id.label("article_id"),
                        other.c.title,
                        other.c.publisher,
                        article_reprints.c.body_similarity,
                        article_reprints.c.matching_basis,
                        article_reprints.c.checked_at,
                    )
                    .select_from(article_reprints.join(other, other.c.id == other_id))
                    .where(
                        or_(
                            article_reprints.c.article_a_id == article_id,
                            article_reprints.c.article_b_id == article_id,
                        ),
                        current_self_hash == own_hash,
                        current_other_hash == other_hash,
                    )
                    .order_by(article_reprints.c.checked_at.desc(), other.c.id)
                )
            )
            .mappings()
            .all()
        )
        return [ReprintInfo.model_validate(dict(row)) for row in rows]
