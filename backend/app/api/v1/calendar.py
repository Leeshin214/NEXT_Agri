from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

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
    current_user: dict = Depends(get_current_user),
    year: Optional[int] = Query(None, ge=1900, le=2200),
    month: Optional[int] = Query(None, ge=1, le=12),
):
    """일정 조회.

    - year + month 가 모두 전달되면 해당 월 범위로 필터.
    - 둘 중 하나라도 없으면 전체 active 일정 반환 (프론트 우측 패널 "전체 일정" 용).
    """
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
    # mode="json": event_date(date), start_time/end_time(time), order_id(UUID)
    # → ISO 문자열로 직렬화. supabase-py(httpx) 호환.
    event = await calendar_service.create_event(
        user_id=current_user["id"],
        data=data.model_dump(mode="json"),
    )
    return {"data": event}


@router.patch("/{event_id}", response_model=SuccessResponse[CalendarEventResponse])
async def update_event(
    event_id: UUID,
    data: CalendarEventUpdate,
    current_user: dict = Depends(get_current_user),
):
    """일정 수정"""
    # mode="json": event_date(date), start_time/end_time(time) ISO 직렬화.
    event = await calendar_service.update_event(
        event_id=event_id,
        user_id=current_user["id"],
        data=data.model_dump(exclude_none=True, mode="json"),
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
