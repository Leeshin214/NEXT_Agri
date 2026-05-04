from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class ProductCreate(BaseModel):
    name: str
    category: str
    origin: Optional[str] = None
    spec: Optional[str] = None
    unit: str
    price_per_unit: int
    stock_quantity: int = 0
    min_order_qty: int = 1
    description: Optional[str] = None


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    origin: Optional[str] = None
    spec: Optional[str] = None
    unit: Optional[str] = None
    price_per_unit: Optional[int] = None
    stock_quantity: Optional[int] = None
    min_order_qty: Optional[int] = None
    status: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None


class ProductResponse(BaseModel):
    id: UUID
    seller_id: UUID
    name: str
    category: str
    origin: Optional[str] = None
    spec: Optional[str] = None
    unit: str
    price_per_unit: int
    stock_quantity: int
    min_order_qty: Optional[int] = None
    status: str
    description: Optional[str] = None
    image_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ===========================================
# 상품 상세 페이지용 보강 응답 (B.1, 2026-05-04)
# ===========================================
class ProductMinimal(BaseModel):
    """같은 판매자의 다른 상품 미니 카드용 — 상세 페이지 사이드 노출."""

    id: UUID
    name: str
    category: str
    unit: str
    price_per_unit: int
    stock_quantity: int
    status: str
    image_url: Optional[str] = None

    model_config = {"from_attributes": True}


class ProductDetailResponse(ProductResponse):
    """GET /products/{id}/detail 전용 응답.

    - seller_name / seller_company: users 테이블 조인.
    - partner_relationship_status: 현재 사용자(BUYER)와 판매자 사이 partners 관계 상태.
        값: 'ACTIVE' | 'PENDING_OUTGOING' | 'PENDING_INCOMING' | 'INACTIVE' | None
        (None 이면 거래처 등록 이력 자체 없음)
    - previous_order_count: 본인과 이 판매자 사이의 주문 총 건수.
        soft-deleted/CANCELLED 제외. completed_order_count 는 그 중 COMPLETED 만.
        SELLER 가 본인 상세를 조회하면 두 카운트 모두 0 (의미 없음).
    - other_seller_products: 같은 판매자의 다른 상품 (본 상품 제외, 최대 4개,
        OUT_OF_STOCK 우선순위 낮춤, status != OUT_OF_STOCK 우선).
    """

    seller_name: Optional[str] = None
    seller_company: Optional[str] = None
    partner_relationship_status: Optional[str] = None
    previous_order_count: int = 0
    completed_order_count: int = 0
    other_seller_products: list[ProductMinimal] = []

    model_config = {"from_attributes": True}
