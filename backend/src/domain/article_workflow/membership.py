from uuid import UUID

from sqlalchemy import and_, any_, exists, func, literal, or_, select

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
    requests = (
        select(
            collection_requests.c.source,
            func.array_agg(collection_requests.c.id).label("request_ids"),
        )
        .select_from(
            collection_requests.join(
                collection_rule_targets,
                collection_rule_targets.c.rule_id == collection_requests.c.rule_id,
            )
        )
        .where(
            collection_requests.c.source.in_(("naver_news", "bigkinds")),
            collection_requests.c.mode != "preview",
            collection_rule_targets.c.target_id == target_id,
        )
        .group_by(collection_requests.c.source)
        .cte("target_discovery_requests")
        .prefix_with("MATERIALIZED", dialect="postgresql")
    )
    # 반복 발견 전체 집계 대신 동일 출처의 첫 일치에서 탐색 중단
    discovered = (
        select(collection_request_items.c.source_id)
        .where(
            collection_request_items.c.source_id == material_sources.c.source_id,
            collection_request_items.c.request_id == any_(requests.c.request_ids),
        )
        .correlate(material_sources, requests)
        .limit(1)
        .lateral("target_discovery")
    )
    mapped = article_id.in_(
        select(material_sources.c.material_id)
        .select_from(
            material_sources.join(requests, requests.c.source == material_sources.c.source).join(
                discovered, literal(True)
            )
        )
        .where(
            material_sources.c.material_id.not_in(overridden),
            material_sources.c.source.in_(("naver_news", "bigkinds")),
        )
    )
    active = exists(
        select(analysis_targets.c.id).where(
            analysis_targets.c.id == target_id,
            analysis_targets.c.archived_at.is_(None),
        )
    )
    return and_(active, or_(explicit, mapped))
