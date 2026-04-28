"""정기배송(Subscription) API 라우터.

V1.5 Phase 1.
V1.6 — 양방향 승인 모델: 초기 PENDING → accept/reject 엔드포인트 추가.

엔드포인트:
  GET    /subscriptions                          - 내 정기배송 목록
  GET    /subscriptions/{id}                     - 단일 정기배송
  POST   /subscriptions                          - 정기배송 생성 (status=PENDING)
  POST   /subscriptions/{id}/accept              - PENDING → ACTIVE (V1.6)
  POST   /subscriptions/{id}/reject              - PENDING → REJECTED (V1.6)
  PATCH  /subscriptions/{id}                     - 정기배송 수정 (status 등)
  DELETE /subscriptions/{id}                     - 정기배송 soft delete
  POST   /subscriptions/{id}/generate-order      - 이번 회차 주문 생성
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_current_user
from app.schemas.common import SuccessResponse
from app.schemas.subscription import (
    SubscriptionCreate,
    SubscriptionResponse,
    SubscriptionUpdate,
)
from app.services.subscription_service import subscription_service

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


@router.get("", response_model=SuccessResponse[list[SubscriptionResponse]])
async def list_subscriptions(
    subscription_status: Optional[str] = Query(None, alias="status"),
    partner_user_id: Optional[UUID] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=2000),
    current_user: dict = Depends(get_current_user),
):
    """내 정기배송 목록 (buyer 또는 seller 측 모두).

    Query:
      - status: ACTIVE / PAUSED / ENDED / CANCELLED
      - partner_user_id: 상대방 user id 로 필터 (이 거래처와의 정기배송만)
    """
    data, meta = await subscription_service.list_subscriptions(
        user_id=current_user["id"],
        status_filter=subscription_status,
        partner_user_id=partner_user_id,
        page=page,
        limit=limit,
    )
    return {"data": data, "meta": meta.model_dump()}


@router.get("/{subscription_id}", response_model=SuccessResponse[SubscriptionResponse])
async def get_subscription(
    subscription_id: UUID,
    current_user: dict = Depends(get_current_user),
):
    """단일 정기배송 상세."""
    sub = await subscription_service.get_subscription(
        subscription_id=subscription_id,
        user_id=current_user["id"],
    )
    return {"data": sub}


@router.post(
    "",
    response_model=SuccessResponse[SubscriptionResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_subscription(
    payload: SubscriptionCreate,
    current_user: dict = Depends(get_current_user),
):
    """정기배송 생성 — buyer 또는 seller 본인이어야 함."""
    # mode="json": date / UUID 직렬화 호환 (supabase-py / httpx)
    sub = await subscription_service.create_subscription(
        user_id=current_user["id"],
        payload=payload.model_dump(mode="json"),
    )
    return {"data": sub}


@router.post(
    "/{subscription_id}/accept",
    response_model=SuccessResponse[SubscriptionResponse],
)
async def accept_subscription(
    subscription_id: UUID,
    current_user: dict = Depends(get_current_user),
):
    """정기배송 요청 수락 (V1.6).

    조건:
      - subscription 의 당사자(buyer 또는 seller) 본인.
      - status='PENDING' 이어야 함.
      - created_by != user (요청자 본인은 수락 불가).
        * created_by NULL (V1.5 이전 데이터) 인 경우 누구나 수락 허용.
    동작:
      - status='ACTIVE' 로 전환.
      - next_delivery_date 를 start_date 또는 오늘 이후 첫 회차로 재설정.

    400: 상태가 PENDING 이 아님 / 잘못된 입력.
    403: 본인이 만든 요청을 본인이 수락 시도 / 당사자 아님.
    404: subscription 없음 / soft-deleted.
    """
    sub = await subscription_service.accept_subscription(
        subscription_id=subscription_id,
        user_id=current_user["id"],
    )
    return {"data": sub}


@router.post(
    "/{subscription_id}/reject",
    response_model=SuccessResponse[dict],
)
async def reject_subscription(
    subscription_id: UUID,
    current_user: dict = Depends(get_current_user),
):
    """정기배송 요청 거절 (V1.6).

    조건:
      - subscription 의 당사자(buyer 또는 seller) 본인.
      - status='PENDING' 이어야 함.
      - created_by != user (요청자 본인은 거절 불가).
    동작:
      - status='REJECTED' 로 전환 (이력 보존).

    400: 상태가 PENDING 이 아님.
    403: 본인이 만든 요청을 본인이 거절 시도 / 당사자 아님.
    404: subscription 없음 / soft-deleted.
    """
    await subscription_service.reject_subscription(
        subscription_id=subscription_id,
        user_id=current_user["id"],
    )
    return {"data": {"message": "거절되었습니다"}}


@router.patch(
    "/{subscription_id}",
    response_model=SuccessResponse[SubscriptionResponse],
)
async def update_subscription(
    subscription_id: UUID,
    payload: SubscriptionUpdate,
    current_user: dict = Depends(get_current_user),
):
    """정기배송 부분 수정.

    - status 변경 (ACTIVE/PAUSED/ENDED/CANCELLED) 가능
    - frequency / day_of_week / day_of_month / start_date 변경 시
      next_delivery_date 자동 재계산 (서비스 레이어)
    """
    sub = await subscription_service.update_subscription(
        subscription_id=subscription_id,
        user_id=current_user["id"],
        payload=payload.model_dump(exclude_unset=True, mode="json"),
    )
    return {"data": sub}


@router.delete(
    "/{subscription_id}",
    response_model=SuccessResponse[dict],
)
async def delete_subscription(
    subscription_id: UUID,
    current_user: dict = Depends(get_current_user),
):
    """정기배송 soft delete."""
    deleted = await subscription_service.delete_subscription(
        subscription_id=subscription_id,
        user_id=current_user["id"],
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription not found",
        )
    return {"data": {"deleted": True}}


@router.post(
    "/{subscription_id}/generate-order",
    response_model=SuccessResponse[dict],
)
async def generate_order(
    subscription_id: UUID,
    current_user: dict = Depends(get_current_user),
):
    """이번 회차 주문 생성.

    - subscription.next_delivery_date 를 delivery_date 로 사용
    - subscription_round 자동 계산 (기존 주문 수 + 1)
    - 양쪽 user 의 calendar_events 에 SHIPMENT 이벤트 추가
    - subscription.next_delivery_date 다음 회차로 갱신
    - end_date 도달 시 status=ENDED 자동 전환
    """
    order = await subscription_service.generate_order_for_round(
        subscription_id=subscription_id,
        user_id=current_user["id"],
    )
    return {"data": order}
