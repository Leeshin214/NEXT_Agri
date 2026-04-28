from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class PartnerCreate(BaseModel):
    partner_user_id: UUID
    nickname: Optional[str] = None
    notes: Optional[str] = None


class PartnerUpdate(BaseModel):
    nickname: Optional[str] = None
    status: Optional[str] = None
    is_favorite: Optional[bool] = None
    notes: Optional[str] = None


class PartnerResponse(BaseModel):
    id: UUID
    user_id: UUID
    partner_user_id: UUID
    nickname: Optional[str] = None
    status: str
    is_favorite: bool
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    # 조인된 거래처 정보
    partner_name: Optional[str] = None
    partner_company: Optional[str] = None
    partner_role: Optional[str] = None
    partner_phone: Optional[str] = None

    model_config = {"from_attributes": True}


# ===========================================
# 거래처 통계 (V1.5 Phase 1)
# ===========================================
class PartnerStats(BaseModel):
    """GET /partners/{id}/stats 응답.

    - total_orders:         이 거래처와의 주문 총 건수 (CANCELLED 제외, soft-deleted 제외)
    - total_amount:         이 거래처와의 주문 총액
    - last_order_date:      가장 최근 주문 생성일
    - active_subscriptions: 이 거래처와의 ACTIVE 정기배송 개수
    """

    total_orders: int = 0
    total_amount: int = 0
    last_order_date: Optional[date] = None
    active_subscriptions: int = 0

    model_config = {"from_attributes": True}
