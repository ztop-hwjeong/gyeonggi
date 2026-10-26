from typing import Annotated
from uuid import UUID

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, HTTPException, Query

from domain.events.models import EventCreate, EventInfo, EventQuery, EventUpdate
from domain.events.repository import (
    EventConflictError,
    EventError,
    EventNotFoundError,
    EventRepository,
)

router = APIRouter(prefix="/events", tags=["events"], route_class=DishkaRoute)


def _handle(error: EventError) -> HTTPException:
    if isinstance(error, EventNotFoundError):
        return HTTPException(status_code=404, detail=str(error))
    if isinstance(error, EventConflictError):
        return HTTPException(status_code=409, detail=str(error))
    return HTTPException(status_code=503, detail=str(error))


@router.get("")
async def events(
    repository: FromDishka[EventRepository], query: Annotated[EventQuery, Query()]
) -> list[EventInfo]:
    try:
        return await repository.list(query)
    except EventError as error:
        raise _handle(error) from error


@router.post("", status_code=201)
async def create_event(body: EventCreate, repository: FromDishka[EventRepository]) -> EventInfo:
    try:
        return await repository.create(body)
    except EventError as error:
        raise _handle(error) from error


@router.get("/{event_id}")
async def event(event_id: UUID, repository: FromDishka[EventRepository]) -> EventInfo:
    try:
        return await repository.get(event_id)
    except EventError as error:
        raise _handle(error) from error


@router.put("/{event_id}")
async def update_event(
    event_id: UUID, body: EventUpdate, repository: FromDishka[EventRepository]
) -> EventInfo:
    try:
        return await repository.update(event_id, body)
    except EventError as error:
        raise _handle(error) from error


@router.delete("/{event_id}", status_code=204)
async def delete_event(
    event_id: UUID, repository: FromDishka[EventRepository], version: int = Query(ge=1)
) -> None:
    try:
        await repository.delete(event_id, version)
    except EventError as error:
        raise _handle(error) from error
