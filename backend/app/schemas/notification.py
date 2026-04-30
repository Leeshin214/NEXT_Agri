from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel


# ===========================================
# 알림 타입 (DB CHECK 제약과 1:1 동기화)
# ===========================================
NotificationType = Literal[
    "NEW_MESSAGE",
    "COUNTER_OFFER",
    "OFFER_ACCEPTED",
    "OFFER_REJECTED",
    "DELIVERY_DATE_CHANGE",
    "DELIVERY_DATE_ACCEPTED",
    "DELIVERY_DATE_REJECTED",
    "ORDER_STATUS",
]


class NotificationResponse(BaseModel):
    """알림 단건 응답."""

    id: UUID
    user_id: UUID
    type: NotificationType
    title: str
    body: str
    link_url: Optional[str] = None
    order_id: Optional[UUID] = None
    room_id: Optional[UUID] = None
    is_read: bool
    created_at: datetime
    read_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class NotificationListMeta(BaseModel):
    """GET /notifications 응답 meta — 종 아이콘 카운트와 페이지네이션 동시 노출."""

    unread_count: int
    total: int


class UnreadCountResponse(BaseModel):
    """GET /notifications/unread-count 응답 (가벼운 폴링용 fallback)."""

    unread_count: int


class MarkAllReadResponse(BaseModel):
    """POST /notifications/read-all 응답."""

    updated: int
