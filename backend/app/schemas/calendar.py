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

    model_config = {"from_attributes": True}
