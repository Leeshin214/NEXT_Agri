from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_current_user, require_buyer
from app.schemas.common import SuccessResponse
from app.schemas.order import (
    CounterOfferCreate,
    CounterOfferResponse,
    NegotiationHistoryResponse,
    OrderCancel,
    OrderCreate,
    OrderResponse,
    OrderStatusUpdate,
    OrderUpdate,
)
from app.services.order_service import order_service

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("", response_model=SuccessResponse[list[OrderResponse]])
async def list_orders(
    order_status: Optional[str] = None,
    status_in: Optional[list[str]] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=2000),
    current_user: dict = Depends(get_current_user),
):
    """주문 목록 조회 (역할별 자동 필터).

    - order_status: 단일 상태 필터 (backward compat)
    - status_in: 다중 상태 필터 — `?status_in=COMPLETED&status_in=CANCELLED`
                 둘 다 전달 시 status_in 이 우선
    - limit: 운영 안전을 위해 최대 2000 으로 제한
    """
    data, meta = await order_service.list_orders(
        user_id=current_user["id"],
        role=current_user["role"],
        status=order_status,
        status_in=status_in,
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
    # mode="json": date → ISO 문자열, UUID → str. supabase-py(httpx) JSON 직렬화 호환.
    order = await order_service.create_order(
        buyer_id=current_user["id"],
        data=data.model_dump(mode="json"),
    )
    return {"data": order}


@router.patch("/{order_id}", response_model=SuccessResponse[OrderResponse])
async def update_order(
    order_id: UUID,
    data: OrderUpdate,
    current_user: dict = Depends(get_current_user),
):
    """견적 요청 수정 (QUOTE_REQUESTED 상태 + buyer 본인만)"""
    # mode="json": date/UUID 등 supabase-py(httpx) JSON 직렬화 호환.
    order = await order_service.update_order(
        order_id=order_id,
        payload=data.model_dump(exclude_unset=True, mode="json"),
        user=current_user,
    )
    return {"data": order}


@router.patch("/{order_id}/status", response_model=SuccessResponse[OrderResponse])
async def update_order_status(
    order_id: UUID,
    data: OrderStatusUpdate,
    current_user: dict = Depends(get_current_user),
):
    """주문 상태 변경 (전이/역할 가드 적용)"""
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


@router.patch("/{order_id}/cancel", response_model=SuccessResponse[OrderResponse])
async def cancel_order(
    order_id: UUID,
    data: OrderCancel,
    current_user: dict = Depends(get_current_user),
):
    """주문 취소 — 양쪽 모두 가능, COMPLETED 이후 불가"""
    order = await order_service.cancel_order(
        order_id=order_id,
        reason=data.reason,
        user=current_user,
    )
    return {"data": order}


# ===========================================
# 협상 (counter-offer) 엔드포인트
# ===========================================


@router.post(
    "/{order_id}/counter-offers",
    response_model=SuccessResponse[CounterOfferResponse],
    status_code=201,
)
async def submit_counter_offer(
    order_id: UUID,
    data: CounterOfferCreate,
    current_user: dict = Depends(get_current_user),
):
    """협상가 제시 — 주문 당사자, QUOTE_REQUESTED 또는 NEGOTIATING 상태일 때만"""
    # mode="json": proposed_items 안의 product_id (UUID) 등 JSON 직렬화 호환.
    offer = await order_service.submit_counter_offer(
        order_id=order_id,
        payload=data.model_dump(mode="json"),
        user=current_user,
    )
    return {"data": offer}


@router.post(
    "/{order_id}/counter-offers/{offer_id}/accept",
    response_model=SuccessResponse[CounterOfferResponse],
)
async def accept_counter_offer(
    order_id: UUID,
    offer_id: UUID,
    current_user: dict = Depends(get_current_user),
):
    """협상가 수락 — 상대방의 PENDING 협상가만"""
    offer = await order_service.accept_counter_offer(
        order_id=order_id,
        offer_id=offer_id,
        user=current_user,
    )
    return {"data": offer}


@router.post(
    "/{order_id}/counter-offers/{offer_id}/reject",
    response_model=SuccessResponse[CounterOfferResponse],
)
async def reject_counter_offer(
    order_id: UUID,
    offer_id: UUID,
    current_user: dict = Depends(get_current_user),
):
    """협상가 거절 — 상대방의 PENDING 협상가만"""
    offer = await order_service.reject_counter_offer(
        order_id=order_id,
        offer_id=offer_id,
        user=current_user,
    )
    return {"data": offer}


@router.get(
    "/{order_id}/counter-offers",
    response_model=SuccessResponse[list[NegotiationHistoryResponse]],
)
async def list_counter_offers(
    order_id: UUID,
    current_user: dict = Depends(get_current_user),
):
    """주문 협상 이력 조회 — 주문 당사자만"""
    history = await order_service.list_negotiation_history(
        order_id=order_id,
        user=current_user,
    )
    return {"data": history}
