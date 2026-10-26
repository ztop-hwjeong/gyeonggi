from typing import Annotated
from uuid import UUID

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, HTTPException, Query

from domain.analysis.registry_models import ArticleTopicOverride
from domain.collection.models import MaterialKind
from domain.tag_folders.material_tags import MaterialTagLink, MaterialTags
from domain.tag_folders.models import (
    FolderCreate,
    FolderInfo,
    FolderQuery,
    FolderTagAttach,
    FolderTagMove,
    FolderUpdate,
    TagInfo,
    TagQuery,
    UnfiledTagSummary,
)
from domain.tag_folders.repository import (
    TagFolderConflictError,
    TagFolderError,
    TagFolderNotFoundError,
    TagFolderRepository,
)

router = APIRouter(tags=["tag-folders"], route_class=DishkaRoute)


def _handle(error: TagFolderError) -> HTTPException:
    if isinstance(error, TagFolderNotFoundError):
        return HTTPException(status_code=404, detail=str(error))
    if isinstance(error, TagFolderConflictError):
        return HTTPException(status_code=409, detail=str(error))
    return HTTPException(status_code=503, detail=str(error))


@router.get("/materials/{material_id}/tags")
async def material_tags(
    material_id: UUID, repository: FromDishka[MaterialTags]
) -> list[MaterialTagLink]:
    try:
        return await repository.links(material_id)
    except TagFolderError as error:
        raise _handle(error) from error


@router.put("/materials/{material_id}/tags/{tag_id}", status_code=204)
async def override_material_tag(
    material_id: UUID,
    tag_id: str,
    body: ArticleTopicOverride,
    repository: FromDishka[MaterialTags],
) -> None:
    try:
        await repository.override(material_id, tag_id, body)
    except TagFolderError as error:
        raise _handle(error) from error


@router.get("/tags")
async def tags(
    repository: FromDishka[TagFolderRepository], query: Annotated[TagQuery, Query()]
) -> list[TagInfo]:
    try:
        return await repository.tags(query)
    except TagFolderError as error:
        raise _handle(error) from error


@router.get("/tags/unfiled/summary")
async def unfiled_summary(
    repository: FromDishka[TagFolderRepository],
    inclusion: str = Query(default="all", pattern="^(all|included|excluded)$"),
    kind: MaterialKind | None = None,
) -> UnfiledTagSummary:
    try:
        return await repository.unfiled_summary(inclusion, kind)
    except TagFolderError as error:
        raise _handle(error) from error


@router.get("/tag-folders")
async def folders(
    repository: FromDishka[TagFolderRepository], query: Annotated[FolderQuery, Query()]
) -> list[FolderInfo]:
    try:
        return await repository.folders(query)
    except TagFolderError as error:
        raise _handle(error) from error


@router.post("/tag-folders", status_code=201)
async def create_folder(
    body: FolderCreate, repository: FromDishka[TagFolderRepository]
) -> FolderInfo:
    try:
        return await repository.save_folder(body)
    except TagFolderError as error:
        raise _handle(error) from error


@router.post("/tag-folders/tag-moves", status_code=204)
async def move_tag(body: FolderTagMove, repository: FromDishka[TagFolderRepository]) -> None:
    try:
        await repository.move_tag(body)
    except TagFolderError as error:
        raise _handle(error) from error


@router.put("/tag-folders/{folder_id}")
async def update_folder(
    folder_id: UUID, body: FolderUpdate, repository: FromDishka[TagFolderRepository]
) -> FolderInfo:
    try:
        return await repository.save_folder(body, folder_id)
    except TagFolderError as error:
        raise _handle(error) from error


@router.delete("/tag-folders/{folder_id}", status_code=204)
async def delete_folder(
    folder_id: UUID, repository: FromDishka[TagFolderRepository], version: int = Query(ge=1)
) -> None:
    try:
        await repository.delete_folder(folder_id, version)
    except TagFolderError as error:
        raise _handle(error) from error


@router.post("/tag-folders/{folder_id}/tags", status_code=204)
async def attach_tags(
    folder_id: UUID, body: FolderTagAttach, repository: FromDishka[TagFolderRepository]
) -> None:
    try:
        await repository.attach_tags(folder_id, body)
    except TagFolderError as error:
        raise _handle(error) from error


@router.delete("/tag-folders/{folder_id}/tags/{tag_id}", status_code=204)
async def detach_tag(
    folder_id: UUID, tag_id: str, repository: FromDishka[TagFolderRepository]
) -> None:
    try:
        await repository.detach_tag(folder_id, tag_id)
    except TagFolderError as error:
        raise _handle(error) from error
