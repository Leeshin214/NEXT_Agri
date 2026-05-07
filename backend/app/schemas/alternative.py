"""대체 거래처 추천 (alternative_partner_recommendations) Pydantic 스키마.

저장된 JSONB candidates 의 각 원소는 alternative_partner_service 가 정규화한 키 셋을 갖는다.
프론트엔드는 이 응답을 그대로 받아 카드 리스트로 렌더한다.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class AlternativeCandidate(BaseModel):
    seller_id: UUID
    seller_name: str = ""
    seller_company: str = ""
    product_id: UUID
    product_name: str = ""
    stock_quantity: int = 0
    price_per_unit: int = 0
    unit: str = ""
    trade_count: int = 0
    last_trade_date: Optional[datetime] = None
    # 자동 생성된 견적 주문 — 실패한 후보는 None / error 메시지가 들어옴
    auto_order_id: Optional[UUID] = None
    auto_order_number: Optional[str] = None
    auto_order_error: Optional[str] = None
    # 가격 결정 메타 (2026-05-07) — 옛 row 호환을 위해 모두 Optional
    original_unit_price: Optional[int] = None
    effective_unit_price: Optional[int] = None
    # ORIGINAL_LOWER / CANDIDATE_LOWER / EQUAL / FALLBACK_ORIGINAL / FALLBACK_CANDIDATE
    price_strategy: Optional[str] = None


class AlternativeRecommendationResponse(BaseModel):
    id: UUID
    cancelled_order_id: UUID
    buyer_id: UUID
    candidates: list[AlternativeCandidate]
    reason: str
    found_count: int
    created_at: datetime

    model_config = {"from_attributes": True}
