from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class ChatRoomCreate(BaseModel):
    partner_user_id: UUID
    order_id: Optional[UUID] = None


class ChatRoomResponse(BaseModel):
    id: UUID
    order_id: Optional[UUID] = None
    seller_id: UUID
    buyer_id: UUID
    last_message: Optional[str] = None
    last_message_at: Optional[datetime] = None
    created_at: datetime
    # 조인 정보
    partner_name: Optional[str] = None
    partner_company: Optional[str] = None
    unread_count: int = 0

    model_config = {"from_attributes": True}


class MessageCreate(BaseModel):
    content: str


class MessageResponse(BaseModel):
    id: UUID
    room_id: UUID
    sender_id: UUID
    content: str
    is_read: bool
    created_at: datetime
    deleted_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
