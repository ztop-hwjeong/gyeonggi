from sqlalchemy import exists, select

from domain.analysis.tables import material_tags
from domain.collection.tables import materials


def tagged_materials(tag_ids: set[str], kind: str | None = None):
    criteria = [
        materials.c.kind.in_(("news", "blog")),
        material_tags.c.material_id == materials.c.id,
        material_tags.c.topic_id.in_(tag_ids),
        material_tags.c.origin.in_(("ai", "manual_include")),
    ]
    if kind is not None:
        criteria.append(materials.c.kind == kind)
    return exists(select(material_tags.c.material_id).where(*criteria))
