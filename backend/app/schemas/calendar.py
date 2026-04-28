from datetime import date, datetime, time
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class CalendarEventCreate(BaseModel):
    order_id: Optional[UUID] = None
    title: str
    event_type: str
    event_date: date
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    description: Optional[str] = None
    is_allday: bool = True


class CalendarEventUpdate(BaseModel):
    title: Optional[str] = None
    event_type: Optional[str] = None
    event_date: Optional[date] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    description: Optional[str] = None
    is_allday: Optional[bool] = None


class CalendarEventResponse(BaseModel):
    id: UUID
    user_id: UUID
    order_id: Optional[UUID] = None
    title: str
    event_type: str
    event_date: date
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    description: Optional[str] = None
    is_allday: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    # 주문 연결된 일정의 부가 정보 (order_id 가 None 이거나 주문/상품이 soft-delete 된 경우 None)
    order_number: Optional[str] = None
    product_name: Optional[str] = None
    # 주문 상태 — calendar_events.event_type 은 ORDER 로 고정되므로
    # 프론트가 색상/배지 구분용으로 사용한다.
    # QUOTE_REQUESTED | NEGOTIATING | CONFIRMED | PREPARING | SHIPPING | COMPLETED | CANCELLED
    order_status: Optional[str] = None

    model_config = {"from_attributes": True}
