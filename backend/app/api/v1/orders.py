from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_current_user, require_buyer
from app.schemas.common import SuccessResponse
from app.schemas.order import OrderCreate, OrderResponse, OrderStatusUpdate
from app.services.order_service import order_service

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("", response_model=SuccessResponse[list[OrderResponse]])
async def list_orders(
    order_status: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
):
    """주문 목록 조회 (역할별 자동 필터)"""
    data, meta = await order_service.list_orders(
        user_id=current_user["id"],
        role=current_user["role"],
        status=order_status,
        page=page,
        limit=limit,
    )
    return {"data": data, "meta": meta.model_dump()}


@router.get("/{order_id}", response_model=SuccessResponse[OrderResponse])
async def get_order(
    order_id: UUID,
    current_user: dict = Depends(get_current_user),
):
    """주문 상세 조회"""
    order = await order_service.get_order(order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Order not found"
        )

    # 본인이 관련된 주문만 조회 가능
    user_id = current_user["id"]
    if order["buyer_id"] != user_id and order["seller_id"] != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
        )

    return {"data": order}


@router.post("", response_model=SuccessResponse[OrderResponse], status_code=201)
async def create_order(
    data: OrderCreate,
    current_user: dict = Depends(require_buyer),
):
    """견적 요청 (구매자만)"""
    order = await order_service.create_order(
        buyer_id=current_user["id"],
        data=data.model_dump(),
    )
    return {"data": order}


@router.patch("/{order_id}/status", response_model=SuccessResponse[OrderResponse])
async def update_order_status(
    order_id: UUID,
    data: OrderStatusUpdate,
    current_user: dict = Depends(get_current_user),
):
    """주문 상태 변경"""
    order = await order_service.update_status(
        order_id=order_id,
        user_id=current_user["id"],
        new_status=data.status,
    )
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Order not found"
        )
    return {"data": order}
