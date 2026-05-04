from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_current_user, require_seller
from app.schemas.common import SuccessResponse
from app.schemas.product import (
    ProductCreate,
    ProductDetailResponse,
    ProductResponse,
    ProductUpdate,
)
from app.services.product_service import product_service

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=SuccessResponse[list[ProductResponse]])
async def list_products(
    category: Optional[str] = None,
    product_status: Optional[str] = None,
    seller_id: Optional[UUID] = None,
    search: Optional[str] = None,
    max_price: Optional[int] = Query(default=None, ge=0, description="단가 상한 필터 (price_per_unit <= max_price)"),
    min_stock: Optional[int] = Query(default=None, ge=0, description="재고 하한 필터 (stock_quantity >= min_stock)"),
    page: int = 1,
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
):
    """상품 목록 조회. 판매자는 자신의 상품, 구매자는 전체 조회."""
    effective_seller_id = seller_id
    if current_user["role"] == "SELLER" and not seller_id:
        effective_seller_id = current_user["id"]

    data, meta = await product_service.list_products(
        seller_id=effective_seller_id,
        category=category,
        status=product_status,
        search=search,
        max_price=max_price,
        min_stock=min_stock,
        page=page,
        limit=limit,
    )
    return {"data": data, "meta": meta.model_dump()}


@router.get("/{product_id}", response_model=SuccessResponse[ProductResponse])
async def get_product(
    product_id: UUID,
    current_user: dict = Depends(get_current_user),
):
    """상품 상세 조회 (단순 응답 — 호환성 유지).

    상세 페이지에서 추가 컨텍스트(판매자 join, 거래 이력, 같은 판매자의 다른 상품)가
    필요하면 GET /products/{id}/detail 사용. 이 엔드포인트는 ProductResponse 스키마만 보장.
    """
    product = await product_service.get_product(product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
        )
    return {"data": product}


@router.get(
    "/{product_id}/detail",
    response_model=SuccessResponse[ProductDetailResponse],
)
async def get_product_detail(
    product_id: UUID,
    current_user: dict = Depends(get_current_user),
):
    """상품 상세 페이지 전용 — 판매자 정보 + 거래 관계 + 같은 판매자 다른 상품을 한 번에 반환 (B.1, 2026-05-04).

    응답 (ProductDetailResponse):
      - ProductResponse 의 모든 필드
      - seller_name / seller_company: users 테이블 조인
      - partner_relationship_status: 현재 사용자 ↔ 판매자 partners.status
        (BUYER 만 채워짐. SELLER 본인 조회 시 None.)
        값: 'ACTIVE' | 'PENDING_OUTGOING' | 'PENDING_INCOMING' | 'INACTIVE' | None
      - previous_order_count: BUYER 와 이 판매자 사이 주문 총 건수 (CANCELLED/soft-deleted 제외)
      - completed_order_count: 그 중 status='COMPLETED' 만
      - other_seller_products: 같은 판매자의 다른 상품 (최대 4개, OUT_OF_STOCK 후순위)

    가드:
      - 상품이 없거나 soft-deleted → 404
      - 상품의 판매자가 soft-deleted 면 SELLER 본인 외엔 404 (구매자에게 노출 차단)
    """
    product = await product_service.get_product_detail(
        product_id=product_id,
        current_user_id=current_user["id"],
        current_user_role=current_user["role"],
    )
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
        )
    return {"data": product}


@router.post("", response_model=SuccessResponse[ProductResponse], status_code=201)
async def create_product(
    data: ProductCreate,
    current_user: dict = Depends(require_seller),
):
    """상품 등록 (판매자만)"""
    product = await product_service.create_product(
        seller_id=current_user["id"],
        data=data.model_dump(),
    )
    return {"data": product}


@router.patch("/{product_id}", response_model=SuccessResponse[ProductResponse])
async def update_product(
    product_id: UUID,
    data: ProductUpdate,
    current_user: dict = Depends(require_seller),
):
    """상품 수정 (판매자만, 본인 소유)"""
    product = await product_service.update_product(
        product_id=product_id,
        seller_id=current_user["id"],
        data=data.model_dump(exclude_none=True),
    )
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
        )
    return {"data": product}


@router.delete("/{product_id}", status_code=204)
async def delete_product(
    product_id: UUID,
    current_user: dict = Depends(require_seller),
):
    """상품 삭제 (판매자만, soft delete)"""
    deleted = await product_service.delete_product(
        product_id=product_id,
        seller_id=current_user["id"],
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
        )
