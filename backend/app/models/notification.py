from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Notification(Base):
    """사용자 알림 (우상단 종 아이콘 패턴).

    - 가격 협상(COUNTER_OFFER / OFFER_ACCEPTED / OFFER_REJECTED)
    - 납품일 변경(DELIVERY_DATE_CHANGE / _ACCEPTED / _REJECTED)
    - 주문 상태 변경(ORDER_STATUS)
    - 신규 채팅 메시지(NEW_MESSAGE)

    채팅 시스템 메시지(messages 테이블)와 별개로 알림 패널 전용.
    INSERT 는 service_role 만(서버 emit), SELECT/UPDATE 는 본인만(RLS).
    """

    __tablename__ = "notifications"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # NEW_MESSAGE | COUNTER_OFFER | OFFER_ACCEPTED | OFFER_REJECTED
    # | DELIVERY_DATE_CHANGE | DELIVERY_DATE_ACCEPTED | DELIVERY_DATE_REJECTED
    # | ORDER_STATUS
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    link_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    order_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="SET NULL"),
        nullable=True,
    )
    room_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_rooms.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_read: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    read_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
