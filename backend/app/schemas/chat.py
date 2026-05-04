from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ChatRoomCreate(BaseModel):
    partner_user_id: UUID
    order_id: Optional[UUID] = None
    # 상품 문의로 진입한 경우 — 새로 생성되는 채팅방의 첫 시스템 메시지 metadata 에
    # {kind: 'product_inquiry', inquiry_product_id} 로 저장됨 (B.2, 2026-05-04).
    # 기존 채팅방을 반환하는 경우엔 이 필드는 무시 (메시지 자동 발송 X).
    inquiry_product_id: Optional[UUID] = None


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


# AI 답장 초안 — POST /chat/draft (2026-05-03 추가)
# 채팅방 입력창에 `/초안 ...` 명령으로 호출. 메시지 DB 저장 안 함.
class ChatDraftRequest(BaseModel):
    room_id: UUID
    instruction: str = Field(..., min_length=1, max_length=500)


class ChatDraftResponse(BaseModel):
    draft: str


# 협상 의도 감지 — US-2 (2026-05-04 추가)
# 평문 메시지에서 가격 협상 의도 감지 → metadata.draft_negotiation 저장 + WS 푸시.
# 자동 등록 절대 X — 발신자 본인이 [등록] 클릭 시 기존 propose_counter_offer 흐름 사용.
class NegotiationDraft(BaseModel):
    """messages.metadata['draft_negotiation'] JSONB 구조 (검증/문서화 목적)."""
    product_name: Optional[str] = None
    quantity: Optional[int] = None
    unit: Optional[str] = None  # kg | box | piece | bag | 개 | 포대 등
    unit_price: Optional[int] = None  # KRW 정수
    confidence: float = 0.0  # 0.0 ~ 1.0
    detected_at: Optional[datetime] = None
    dismissed_at: Optional[datetime] = None


class NegotiationDraftDismissResponse(BaseModel):
    """PATCH /chat/messages/{message_id}/dismiss-draft-negotiation 응답."""
    message_id: UUID
    draft_negotiation: NegotiationDraft
