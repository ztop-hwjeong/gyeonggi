from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from domain.templates.archive import TemplateArchive
from domain.templates.catalog import TemplateCatalog, TemplateNotFoundError
from domain.templates.models import TemplateReference, TemplateVersion
from domain.templates.rendering import TemplateInputError, TemplateRenderer, TemplateRenderError

router = APIRouter(prefix="/templates", tags=["templates"], route_class=DishkaRoute)


class TemplateRenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: dict[str, JsonValue]


@router.post(
    "/{code}/versions/{version}/render",
    response_class=Response,
    responses={
        200: {
            "content": {
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {
                    "schema": {"type": "string", "format": "binary"}
                }
            }
        }
    },
)
async def render_template(
    code: str, version: str, request: TemplateRenderRequest, renderer: FromDishka[TemplateRenderer]
) -> Response:
    try:
        content = await run_in_threadpool(renderer.render, code, version, request.data)
    except TemplateNotFoundError as error:
        raise HTTPException(status_code=404, detail="템플릿 버전 없음") from error
    except TemplateInputError as error:
        raise HTTPException(status_code=422, detail=error.errors) from error
    except TemplateRenderError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{code}-{version}-report.xlsx"'},
    )


class TemplateArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    templates: tuple[TemplateReference, ...] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def unique_templates(self) -> "TemplateArchiveRequest":
        if len(set(self.templates)) != len(self.templates):
            raise ValueError("템플릿 코드·버전 중복")
        return self


@router.post(
    "/archive",
    response_class=Response,
    responses={
        200: {"content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}}},
        404: {"description": "템플릿 버전 없음"},
    },
)
async def download_archive(
    request: TemplateArchiveRequest, archive: FromDishka[TemplateArchive]
) -> Response:
    try:
        content = await run_in_threadpool(archive.build, request.templates)
    except TemplateNotFoundError as error:
        raise HTTPException(status_code=404, detail="템플릿 버전 없음") from error
    return Response(
        content,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="templates.zip"'},
    )


@router.get("")
async def list_templates(catalog: FromDishka[TemplateCatalog]) -> list[TemplateVersion]:
    return catalog.list_versions()


@router.get("/{code}/versions")
async def list_versions(code: str, catalog: FromDishka[TemplateCatalog]) -> list[TemplateVersion]:
    versions = catalog.list_versions(code)
    if not versions:
        raise HTTPException(status_code=404, detail="템플릿 없음")
    return versions


@router.get("/{code}/versions/{version}", responses={404: {"description": "템플릿 버전 없음"}})
async def get_template(
    code: str, version: str, catalog: FromDishka[TemplateCatalog]
) -> TemplateVersion:
    try:
        return catalog.get(code, version)
    except TemplateNotFoundError as error:
        raise HTTPException(status_code=404, detail="템플릿 버전 없음") from error


@router.get(
    "/{code}/versions/{version}/file",
    response_class=FileResponse,
    responses={404: {"description": "템플릿 버전 없음"}},
)
async def download_template(
    code: str, version: str, catalog: FromDishka[TemplateCatalog]
) -> FileResponse:
    try:
        path = catalog.file(code, version)
    except TemplateNotFoundError as error:
        raise HTTPException(status_code=404, detail="템플릿 버전 없음") from error
    return FileResponse(
        path,
        filename=f"{code}-{version}.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
