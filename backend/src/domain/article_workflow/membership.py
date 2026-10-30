from uuid import UUID

from sqlalchemy import and_, exists, or_, select

from domain.article_workflow.tables import analysis_targets, article_target_links
from domain.collection.tables import (
    collection_request_items,
    collection_requests,
    collection_rule_targets,
    material_sources,
)


def is_target_member(article_id, target_id: UUID):
    """명시 판단을 우선하는 활성 분석 대상 연결 확인."""
    explicit = article_id.in_(
        select(article_target_links.c.article_id).where(
            article_target_links.c.target_id == target_id,
            article_target_links.c.decision == "include",
        )
    )
    overridden = select(article_target_links.c.article_id).where(
        article_target_links.c.target_id == target_id,
    )
    # 반복 발견을 먼저 줄여 기사·요청 간 대량 교차 조인 방지
    discovered = (
        select(collection_requests.c.source, collection_request_items.c.source_id)
        .select_from(
            collection_requests.join(
                collection_request_items,
                collection_requests.c.id == collection_request_items.c.request_id,
            )
            .join(
                collection_rule_targets,
                collection_rule_targets.c.rule_id == collection_requests.c.rule_id,
            )
            .join(
                analysis_targets,
                analysis_targets.c.id == collection_rule_targets.c.target_id,
            )
        )
        .where(
            collection_requests.c.source.in_(("naver_news", "bigkinds")),
            collection_requests.c.mode != "preview",
            collection_rule_targets.c.target_id == target_id,
            analysis_targets.c.archived_at.is_(None),
        )
        .distinct()
        .cte("target_discovered_sources")
        .prefix_with("MATERIALIZED", dialect="postgresql")
    )
    mapped = article_id.in_(
        select(material_sources.c.material_id)
        .select_from(
            material_sources.join(
                discovered,
                and_(
                    discovered.c.source == material_sources.c.source,
                    discovered.c.source_id == material_sources.c.source_id,
                ),
            )
        )
        .where(
            material_sources.c.material_id.not_in(overridden),
        )
    )
    active = exists(
        select(analysis_targets.c.id).where(
            analysis_targets.c.id == target_id,
            analysis_targets.c.archived_at.is_(None),
        )
    )
    return and_(active, or_(explicit, mapped))
