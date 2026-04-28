"""정기배송(Subscription) Pydantic 스키마.

V1.5 Phase 1 — subscriptions / subscription_items 테이블에 대응.
V1.6        — PENDING / REJECTED 상태 + created_by 필드 추가 (양방향 승인 모델).
"""
from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ===========================================
# 빈도 / 상태 상수 (참고용)
# ===========================================
SUBSCRIPTION_FREQUENCIES = ("WEEKLY", "BIWEEKLY", "MONTHLY")
# V1.6: PENDING (요청 직후, 상대 수락 대기) / REJECTED (상대가 거절) 추가
SUBSCRIPTION_STATUSES = (
    "PENDING",
    "ACTIVE",
    "PAUSED",
    "ENDED",
    "CANCELLED",
    "REJECTED",
)


# ===========================================
# Subscription Items
# ===========================================
class SubscriptionItemCreate(BaseModel):
    product_id: UUID
    quantity: int = Field(..., gt=0)
    unit_price: int = Field(..., ge=0)
    unit: str


class SubscriptionItemResponse(BaseModel):
    id: UUID
    subscription_id: UUID
    product_id: UUID
    quantity: int
    unit_price: int
    unit: str
    created_at: datetime
    # join 필드 — products(name) 임베딩에서 평탄화. 상품 soft-delete 시 None.
    product_name: Optional[str] = None

    model_config = {"from_attributes": True}


# ===========================================
# Subscription
# ===========================================
class SubscriptionCreate(BaseModel):
    seller_id: UUID
    buyer_id: UUID
    partner_id: Optional[UUID] = None
    frequency: str  # WEEKLY / BIWEEKLY / MONTHLY
    day_of_week: Optional[int] = Field(default=None, ge=0, le=6)
    day_of_month: Optional[int] = Field(default=None, ge=1, le=31)
    start_date: date
    end_date: Optional[date] = None
    delivery_address: Optional[str] = None
    notes: Optional[str] = None
    items: list[SubscriptionItemCreate]


class SubscriptionUpdate(BaseModel):
    """부분 수정. 미전달 필드는 변경하지 않는다."""

    frequency: Optional[str] = None
    day_of_week: Optional[int] = Field(default=None, ge=0, le=6)
    day_of_month: Optional[int] = Field(default=None, ge=1, le=31)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: Optional[str] = None
    delivery_address: Optional[str] = None
    notes: Optional[str] = None


class SubscriptionResponse(BaseModel):
    id: UUID
    seller_id: UUID
    buyer_id: UUID
    partner_id: Optional[UUID] = None
    frequency: str
    day_of_week: Optional[int] = None
    day_of_month: Optional[int] = None
    start_date: date
    end_date: Optional[date] = None
    next_delivery_date: date
    status: str  # PENDING / ACTIVE / PAUSED / ENDED / CANCELLED / REJECTED
    delivery_address: Optional[str] = None
    notes: Optional[str] = None
    total_amount: int
    # V1.6: 정기배송을 만든 사용자 (수락 권한 판단용)
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    items: list[SubscriptionItemResponse] = []

    # 거래처 상대방 정보 (편의)
    seller_name: Optional[str] = None
    seller_company: Optional[str] = None
    buyer_name: Optional[str] = None
    buyer_company: Optional[str] = None

    model_config = {"from_attributes": True}
