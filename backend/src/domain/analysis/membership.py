from sqlalchemy import and_, func, select

from domain.analysis.tables import article_topics
from domain.collection.tables import material_sources, materials


def tagged_materials(tag_ids: set[str], kind: str | None = None):
    linked = article_topics.join(
        material_sources,
        and_(
            article_topics.c.source == material_sources.c.source,
            article_topics.c.source_id == material_sources.c.source_id,
        ),
    )
    criteria = [
        material_sources.c.material_id == materials.c.id,
        materials.c.kind.in_(("news", "blog")),
        article_topics.c.topic_id.in_(tag_ids),
    ]
    if kind is not None:
        criteria.append(materials.c.kind == kind)
    return (
        select(material_sources.c.material_id)
        .select_from(linked)
        .where(*criteria)
        .group_by(article_topics.c.topic_id, material_sources.c.material_id)
        .having(
            func.bool_or(article_topics.c.origin == "manual_exclude").is_(False),
            func.bool_or(article_topics.c.origin.in_(("ai", "manual_include"))).is_(True),
        )
        .exists()
    )
