from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_current_user, require_seller
from app.schemas.common import SuccessResponse
from app.schemas.product import ProductCreate, ProductResponse, ProductUpdate
from app.services.product_service import product_service

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=SuccessResponse[list[ProductResponse]])
async def list_products(
    category: Optional[str] = None,
    product_status: Optional[str] = None,
    seller_id: Optional[UUID] = None,
    search: Optional[str] = None,
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
        page=page,
        limit=limit,
    )
    return {"data": data, "meta": meta.model_dump()}


@router.get("/{product_id}", response_model=SuccessResponse[ProductResponse])
async def get_product(
    product_id: UUID,
    current_user: dict = Depends(get_current_user),
):
    """상품 상세 조회"""
    product = await product_service.get_product(product_id)
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
