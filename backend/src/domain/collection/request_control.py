from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from domain.article_workflow.tables import analysis_targets
from domain.collection.tables import (
    collection_requests,
    collection_rule_targets,
)


def _has_mapping(rule_id):
    return exists(
        select(collection_rule_targets.c.rule_id).where(
            collection_rule_targets.c.rule_id == rule_id
        )
    )


def _has_collectable_target(rule_id):
    return exists(
        select(collection_rule_targets.c.target_id)
        .select_from(
            collection_rule_targets.join(
                analysis_targets,
                analysis_targets.c.id == collection_rule_targets.c.target_id,
            )
        )
        .where(
            collection_rule_targets.c.rule_id == rule_id,
            analysis_targets.c.archived_at.is_(None),
            analysis_targets.c.collection_enabled.is_(True),
        )
    )


async def has_collectable_target(session: AsyncSession, rule_id: UUID) -> bool:
    """연결이 없거나 수집 가능한 분석 대상 존재 여부."""
    return bool(
        await session.scalar(
            select(or_(~_has_mapping(rule_id), _has_collectable_target(rule_id)))
        )
    )


async def cancel_uncollectable_requests(
    session: AsyncSession, rule_ids: Iterable[UUID]
) -> None:
    """수집 가능한 대상이 사라진 규칙의 진행 전 요청 취소."""
    ids = tuple(set(rule_ids))
    if not ids:
        return
    unavailable = and_(
        collection_requests.c.rule_id.in_(ids),
        _has_mapping(collection_requests.c.rule_id),
        ~_has_collectable_target(collection_requests.c.rule_id),
    )
    await session.execute(
        update(collection_requests)
        .where(unavailable, collection_requests.c.status == "queued")
        .values(status="cancelled", updated_at=func.now())
    )
    await session.execute(
        update(collection_requests)
        .where(
            unavailable,
            collection_requests.c.status.in_(("submitted", "running")),
        )
        .values(status="cancelling", updated_at=func.now())
    )
