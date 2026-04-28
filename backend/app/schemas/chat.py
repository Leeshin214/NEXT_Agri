from datetime import datetime
from typing import Any, Optional
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
    updated_at: datetime
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
    # 주문 협상 ↔ 채팅 양방향 연결 (2026-04-27 추가)
    # message_type 종류:
    #   TEXT            — 일반 사용자 메시지 (기본값)
    #   SYSTEM          — 시스템 안내 메시지
    #   COUNTER_OFFER   — 협상가 제시 (metadata: offer_id, proposed_total_amount, from_role, notes)
    #   OFFER_ACCEPTED  — 협상가 수락 (metadata: offer_id, accepted_amount)
    #   OFFER_REJECTED  — 협상가 거절 (metadata: offer_id)
    #   ORDER_STATUS    — 주문 상태 변경 (metadata: order_id, from_status, to_status)
    #   ORDER_CANCELLED — 주문 취소 (metadata: order_id, reason)
    message_type: str = "TEXT"
    metadata: Optional[dict[str, Any]] = None

    model_config = {"from_attributes": True}


# 주문 협상 ↔ 채팅 메시지 metadata 참고용 스키마 (검증/문서화 목적)
# 실제 DB metadata 컬럼은 JSONB 자유 형식이므로 Optional[dict] 로 그대로 사용해도 무방
class CounterOfferMetadata(BaseModel):
    offer_id: UUID
    proposed_total_amount: int
    from_role: str  # "SELLER" | "BUYER"
    notes: Optional[str] = None
    status: str = "PENDING"  # "PENDING" | "ACCEPTED" | "REJECTED" | "SUPERSEDED"
