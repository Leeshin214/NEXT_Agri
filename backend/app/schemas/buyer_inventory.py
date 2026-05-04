"""구매자(BUYER) 재고 Pydantic 스키마.

- 자동 생성/누적: order_service.update_status() 의 COMPLETED 분기 →
  _add_buyer_inventory_for_order() — 사용자가 직접 INSERT 하지 않으므로 Create 스키마 없음.
- BuyerInventoryUpdate: 수량/메모 수정 (PATCH)
- BuyerInventoryResponse: products + sellers 임베딩 결과 평탄화 — product/seller 정보 포함
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class BuyerInventoryUpdate(BaseModel):
    """수량/메모 수동 조정 (소진 처리 등). 본인 재고만."""

    quantity: Optional[int] = Field(default=None, ge=0)
    notes: Optional[str] = None


class BuyerInventoryResponse(BaseModel):
    """구매자 재고 응답.

    products + sellers 임베딩으로 join 한 결과를 평탄화한 파생 필드를 포함.
    임베딩이 None(상품/판매자 soft-delete 등) 이면 모두 Optional 로 None 처리.
    """

    id: UUID
    buyer_id: UUID
    product_id: UUID
    quantity: int
    unit: Optional[str] = None
    last_added_at: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    # PostgREST embed 파생 필드 (응답 평탄화)
    product_name: Optional[str] = None
    product_category: Optional[str] = None
    product_image_url: Optional[str] = None
    seller_name: Optional[str] = None
    seller_company: Optional[str] = None

    model_config = {"from_attributes": True}
