from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_current_user, require_buyer
from app.schemas.common import SuccessResponse
from app.schemas.order import (
    CancelRequestCreate,
    CancelRequestResponse,
    CancelRequestRespond,
    CounterOfferCreate,
    CounterOfferResponse,
    DeliveryDateChangeCreate,
    DeliveryDateChangeResponse,
    NegotiationHistoryResponse,
    OrderCancel,
    OrderCreate,
    OrderResponse,
    OrderStatusUpdate,
    OrderUpdate,
)
from app.services.order_service import order_service


# KST 기준 오늘 날짜 (납품일 검증용 — UTC 자정 부근 하루 어긋남 방지)
_KST_TZ = timezone(timedelta(hours=9))


def _today_kst():
    return datetime.now(_KST_TZ).date()

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("", response_model=SuccessResponse[list[OrderResponse]])
async def list_orders(
    order_status: Optional[str] = None,
    status_in: Optional[list[str]] = Query(None),
    partner_user_id: Optional[UUID] = Query(
        None,
        description=(
            "특정 거래처(partner의 user_id) 와의 주문만 필터. "
            "내가 buyer이고 상대가 seller, 또는 그 역까지 양방향 매칭."
        ),
    ),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=2000),
    current_user: dict = Depends(get_current_user),
):
    """주문 목록 조회 (역할별 자동 필터).

    - order_status: 단일 상태 필터 (backward compat)
    - status_in: 다중 상태 필터 — `?status_in=COMPLETED&status_in=CANCELLED`
                 둘 다 전달 시 status_in 이 우선
    - partner_user_id: 특정 거래처(상대 user.id) 와의 주문만 (양방향 OR 매칭).
                       역할 기반 자동 필터(buyer_id/seller_id) 와 AND 결합되어
                       (me==buyer AND counterpart==seller) OR
                       (me==seller AND counterpart==buyer) 형태로 적용된다.
    - limit: 운영 안전을 위해 최대 2000 으로 제한
    """
    data, meta = await order_service.list_orders(
        user_id=current_user["id"],
        role=current_user["role"],
        status=order_status,
        status_in=status_in,
        partner_user_id=partner_user_id,
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
    """주문 취소.

    - BUYER: QUOTE_REQUESTED/NEGOTIATING 에서만 직접 취소 가능.
    - BUYER + CONFIRMED: 취소 요청(POST /cancel-request) 을 사용해야 함 → 403.
    - BUYER + PREPARING/SHIPPING: 취소 불가 → 403.
    - SELLER: 모든 활성 상태에서 직접 취소 가능.
    """
    order = await order_service.cancel_order(
        order_id=order_id,
        reason=data.reason,
        user=current_user,
    )
    return {"data": order}


@router.post(
    "/{order_id}/cancel-request",
    response_model=SuccessResponse[CancelRequestResponse],
    status_code=201,
)
async def create_cancel_request(
    order_id: UUID,
    data: CancelRequestCreate,
    current_user: dict = Depends(get_current_user),
):
    """구매자가 CONFIRMED 주문에 대해 판매자에게 취소 승인을 요청한다."""
    req = await order_service.create_cancel_request(
        order_id=order_id,
        reason=data.reason,
        user=current_user,
    )
    return {"data": req}


@router.patch(
    "/{order_id}/cancel-request/{request_id}/respond",
    response_model=SuccessResponse[CancelRequestResponse],
)
async def respond_cancel_request(
    order_id: UUID,
    request_id: UUID,
    data: CancelRequestRespond,
    current_user: dict = Depends(get_current_user),
):
    """판매자가 취소 요청에 승인(approve) 또는 거절(reject) 응답한다."""
    req = await order_service.respond_cancel_request(
        order_id=order_id,
        request_id=request_id,
        action=data.action,
        user=current_user,
    )
    return {"data": req}


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


# ===========================================
# 납품일 변경 (delivery date change) 엔드포인트
# ===========================================


@router.post(
    "/{order_id}/delivery-date-changes",
    response_model=SuccessResponse[DeliveryDateChangeResponse],
    status_code=201,
)
async def submit_delivery_date_change(
    order_id: UUID,
    data: DeliveryDateChangeCreate,
    current_user: dict = Depends(get_current_user),
):
    """납품일 변경 요청 제시 — 주문 당사자, QUOTE_REQUESTED/NEGOTIATING/CONFIRMED 상태일 때만.

    proposed_delivery_date 는 KST 기준 오늘 이상이어야 함 (과거 날짜 불가 → 422).
    이전 PENDING 변경 요청은 SUPERSEDED 처리되고 채팅 메시지 status 도 함께 동기화된다.
    """
    today_kst = _today_kst()
    if data.proposed_delivery_date < today_kst:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="proposed_delivery_date must be today or later (KST)",
        )

    # mode="json": date → ISO 문자열. supabase-py(httpx) JSON 직렬화 호환.
    change = await order_service.submit_delivery_date_change(
        order_id=order_id,
        payload=data.model_dump(mode="json"),
        user=current_user,
    )
    return {"data": change}


@router.post(
    "/{order_id}/delivery-date-changes/{change_id}/accept",
    response_model=SuccessResponse[DeliveryDateChangeResponse],
)
async def accept_delivery_date_change(
    order_id: UUID,
    change_id: UUID,
    current_user: dict = Depends(get_current_user),
):
    """납품일 변경 수락 — 상대방이 제시한 PENDING 만.

    수락 시 부수 효과:
      1) orders.delivery_date 가 proposed_delivery_date 로 갱신
      2) calendar_events 가 양 당사자 새 날짜로 재동기화 (옛 event_date row soft-delete)
      3) DELIVERY_DATE_ACCEPTED 채팅 시스템 메시지 발송
    """
    change = await order_service.accept_delivery_date_change(
        order_id=order_id,
        change_id=change_id,
        user=current_user,
    )
    return {"data": change}


@router.post(
    "/{order_id}/delivery-date-changes/{change_id}/reject",
    response_model=SuccessResponse[DeliveryDateChangeResponse],
)
async def reject_delivery_date_change(
    order_id: UUID,
    change_id: UUID,
    current_user: dict = Depends(get_current_user),
):
    """납품일 변경 거절 — 상대방이 제시한 PENDING 만"""
    change = await order_service.reject_delivery_date_change(
        order_id=order_id,
        change_id=change_id,
        user=current_user,
    )
    return {"data": change}


@router.get(
    "/{order_id}/delivery-date-changes",
    response_model=SuccessResponse[list[DeliveryDateChangeResponse]],
)
async def list_delivery_date_changes(
    order_id: UUID,
    current_user: dict = Depends(get_current_user),
):
    """납품일 변경 요청 이력 — 주문 당사자만, 시간 역순"""
    history = await order_service.list_delivery_date_changes(
        order_id=order_id,
        user=current_user,
    )
    return {"data": history}
