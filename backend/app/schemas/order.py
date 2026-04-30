from datetime import date, datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class OrderItemCreate(BaseModel):
    product_id: UUID
    quantity: int = Field(..., gt=0)
    unit_price: int = Field(..., ge=0)
    notes: Optional[str] = None


class OrderItemUpdate(BaseModel):
    """협상가 또는 견적 수정에서 항목별 단가/수량을 갱신하기 위한 입력"""

    product_id: UUID
    quantity: int = Field(..., gt=0)
    unit_price: int = Field(..., ge=0)
    notes: Optional[str] = None


class OrderItemResponse(BaseModel):
    id: UUID
    order_id: UUID
    product_id: UUID
    quantity: int
    unit_price: int
    subtotal: int
    notes: Optional[str] = None
    created_at: datetime
    # join 필드 — products(name, unit, category) 임베딩에서 평탄화. 상품 soft-delete 시 None 허용.
    product_name: Optional[str] = None
    product_unit: Optional[str] = None
    product_category: Optional[str] = None

    model_config = {"from_attributes": True}


class OrderCreate(BaseModel):
    seller_id: UUID
    delivery_date: Optional[date] = None
    delivery_address: Optional[str] = None
    notes: Optional[str] = None
    items: list[OrderItemCreate]


class OrderUpdate(BaseModel):
    """견적 요청(QUOTE_REQUESTED) 단계에서 buyer 가 수정할 수 있는 필드"""

    delivery_date: Optional[date] = None
    delivery_address: Optional[str] = None
    notes: Optional[str] = None
    items: Optional[list[OrderItemUpdate]] = None


class OrderStatusUpdate(BaseModel):
    status: str


class OrderCancel(BaseModel):
    reason: str = Field(..., min_length=1)


class CounterOfferCreate(BaseModel):
    proposed_total_amount: int = Field(..., ge=0)
    proposed_items: Optional[list[OrderItemUpdate]] = None
    notes: Optional[str] = None


class CounterOfferResponse(BaseModel):
    id: UUID
    order_id: UUID
    from_user_id: UUID
    from_role: str
    proposed_total_amount: int
    proposed_items: Optional[Any] = None
    notes: Optional[str] = None
    status: str
    responded_at: Optional[datetime] = None
    responded_by: Optional[UUID] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class NegotiationHistoryResponse(BaseModel):
    """주문 협상 이력 목록 응답 (CounterOfferResponse 별칭)"""

    id: UUID
    order_id: UUID
    from_user_id: UUID
    from_role: str
    proposed_total_amount: int
    proposed_items: Optional[Any] = None
    notes: Optional[str] = None
    status: str
    responded_at: Optional[datetime] = None
    responded_by: Optional[UUID] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class DeliveryDateChangeCreate(BaseModel):
    """납품일 변경 요청 — 주문 당사자(SELLER/BUYER) 누구나 제시 가능.

    proposed_delivery_date: 새로 제안하는 납품일 (오늘 이상이어야 함)
    notes: 변경 사유 등 자유 텍스트
    """

    proposed_delivery_date: date
    notes: Optional[str] = None


class DeliveryDateChangeResponse(BaseModel):
    """납품일 변경 요청 단건/이력 응답.

    from_user_name / from_user_company 는 router/service 단계에서 동적 주입 (DB 컬럼 X).
    """

    id: UUID
    order_id: UUID
    from_user_id: UUID
    from_role: str
    proposed_delivery_date: date
    notes: Optional[str] = None
    status: str
    responded_at: Optional[datetime] = None
    responded_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    # 동적 주입 (사용자 표시용 — 응답 평탄화 시 join 으로 채움)
    from_user_name: Optional[str] = None
    from_user_company: Optional[str] = None

    model_config = {"from_attributes": True}


class OrderResponse(BaseModel):
    id: UUID
    order_number: str
    buyer_id: UUID
    seller_id: UUID
    status: str
    total_amount: Optional[int] = None
    delivery_date: Optional[date] = None
    delivery_address: Optional[str] = None
    notes: Optional[str] = None
    cancellation_reason: Optional[str] = None
    cancelled_at: Optional[datetime] = None
    cancelled_by: Optional[UUID] = None
    items: list[OrderItemResponse] = []
    # join 필드 — users!buyer_id / users!seller_id 임베딩에서 평탄화. 사용자 soft-delete 시 None 허용.
    buyer_name: Optional[str] = None
    buyer_company: Optional[str] = None
    seller_name: Optional[str] = None
    seller_company: Optional[str] = None
    # V1.5 Phase 2 — 정기배송에서 자동 생성된 주문 추적. 일반 주문은 None.
    subscription_id: Optional[UUID] = None
    subscription_round: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
