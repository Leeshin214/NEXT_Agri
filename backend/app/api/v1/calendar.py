from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_current_user
from app.schemas.calendar import (
    CalendarEventCreate,
    CalendarEventResponse,
    CalendarEventUpdate,
)
from app.schemas.common import SuccessResponse
from app.services.calendar_service import calendar_service

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("", response_model=SuccessResponse[list[CalendarEventResponse]])
async def list_events(
    year: int,
    month: int,
    current_user: dict = Depends(get_current_user),
):
    """월별 일정 조회"""
    events = await calendar_service.list_events(
        user_id=current_user["id"],
        year=year,
        month=month,
    )
    return {"data": events}


@router.post("", response_model=SuccessResponse[CalendarEventResponse], status_code=201)
async def create_event(
    data: CalendarEventCreate,
    current_user: dict = Depends(get_current_user),
):
    """일정 생성"""
    event = await calendar_service.create_event(
        user_id=current_user["id"],
        data=data.model_dump(),
    )
    return {"data": event}


@router.patch("/{event_id}", response_model=SuccessResponse[CalendarEventResponse])
async def update_event(
    event_id: UUID,
    data: CalendarEventUpdate,
    current_user: dict = Depends(get_current_user),
):
    """일정 수정"""
    event = await calendar_service.update_event(
        event_id=event_id,
        user_id=current_user["id"],
        data=data.model_dump(exclude_none=True),
    )
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Event not found"
        )
    return {"data": event}


@router.delete("/{event_id}", status_code=204)
async def delete_event(
    event_id: UUID,
    current_user: dict = Depends(get_current_user),
):
    """일정 삭제"""
    deleted = await calendar_service.delete_event(
        event_id=event_id,
        user_id=current_user["id"],
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Event not found"
        )
