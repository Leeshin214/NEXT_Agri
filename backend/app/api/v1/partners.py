from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_current_user
from app.schemas.common import SuccessResponse
from app.schemas.partner import (
    PartnerCreate,
    PartnerResponse,
    PartnerStats,
    PartnerUpdate,
)
from app.services.partner_service import partner_service

router = APIRouter(prefix="/partners", tags=["partners"])


@router.get("", response_model=SuccessResponse[list[PartnerResponse]])
async def list_partners(
    partner_status: Optional[str] = None,
    search: Optional[str] = None,
    include_last_trade: bool = False,
    page: int = 1,
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
):
    """내 거래처 목록 조회.

    V1.6 — 양방향 승인 모델:
      - status='ACTIVE'           : 양쪽 모두 수락된 활성 거래처
      - status='PENDING_OUTGOING' : 본인이 보낸 요청 (수락 대기)
      - status='PENDING_INCOMING' : 받은 요청 (본인이 수락/거절 가능)
      - status='INACTIVE'         : 거래 종료

    include_last_trade (PM Report #8 작업 5 — 2026-04-28):
      - True  : 각 거래처의 last_trade_date / last_trade_amount 를 채워 반환.
                거래처 페이지 "최근 거래" 컬럼 같이 실제로 필요한 화면에서만 사용.
      - False (default): 두 필드 None 유지 — orders 추가 쿼리 발생 안 함.
                매핑/검색용 호출 (members, orders 페이지의 partner_user_id→partner.id 맵 등)
                에서 불필요한 N+1성 비용 차단.
    """
    data, meta = await partner_service.list_partners(
        user_id=current_user["id"],
        status=partner_status,
        search=search,
        include_last_trade=include_last_trade,
        page=page,
        limit=limit,
    )
    return {"data": data, "meta": meta.model_dump()}


@router.post("", response_model=SuccessResponse[PartnerResponse], status_code=201)
async def create_partner(
    data: PartnerCreate,
    current_user: dict = Depends(get_current_user),
):
    """거래처 등록 요청 — V1.6 양방향 승인 모델.

    동작:
      - 본인 row(PENDING_OUTGOING) + 상대 row(PENDING_INCOMING) 두 row 동시 생성.
      - 상대가 POST /partners/{id}/accept 호출 시 양쪽 ACTIVE 로 전환.
      - 상대가 POST /partners/{id}/reject 호출 시 양쪽 soft-delete.
      - 본인 row 만 응답으로 반환 (PENDING_OUTGOING).

    409:
      - 이미 (ACTIVE / PENDING_*) 상태로 row 존재.
    400:
      - 자기 자신을 거래처로 등록 시도.
    """
    # mode="json": partner_user_id (UUID) → str. supabase-py(httpx) 호환.
    partner = await partner_service.create_partner(
        user_id=current_user["id"],
        data=data.model_dump(mode="json"),
    )
    return {"data": partner}


@router.post("/{partner_id}/accept", response_model=SuccessResponse[PartnerResponse])
async def accept_partner(
    partner_id: UUID,
    current_user: dict = Depends(get_current_user),
):
    """받은 거래처 요청 수락 (V1.6).

    조건:
      - partner_id 의 row 가 본인의 것이고 status='PENDING_INCOMING' 이어야 함.
    동작:
      - 본인 row + 반대편 row 모두 status='ACTIVE' 로 전환.

    400: 상태가 PENDING_INCOMING 이 아닌 경우.
    404: row 가 없거나 본인 소유가 아닌 경우.
    """
    partner = await partner_service.accept_partner(
        partner_id=partner_id,
        user_id=current_user["id"],
    )
    return {"data": partner}


@router.post("/{partner_id}/reject", response_model=SuccessResponse[dict])
async def reject_partner(
    partner_id: UUID,
    current_user: dict = Depends(get_current_user),
):
    """받은 거래처 요청 거절 (V1.6).

    조건:
      - partner_id 의 row 가 본인의 것이고 status='PENDING_INCOMING' 이어야 함.
    동작:
      - 본인 row + 반대편 row 모두 soft-delete.

    400: 상태가 PENDING_INCOMING 이 아닌 경우.
    404: row 가 없거나 본인 소유가 아닌 경우.
    """
    await partner_service.reject_partner(
        partner_id=partner_id,
        user_id=current_user["id"],
    )
    return {"data": {"message": "거절되었습니다"}}


@router.patch("/{partner_id}", response_model=SuccessResponse[PartnerResponse])
async def update_partner(
    partner_id: UUID,
    data: PartnerUpdate,
    current_user: dict = Depends(get_current_user),
):
    """거래처 정보 수정 (별칭, 즐겨찾기 등)"""
    # mode="json": 일관성 (현재 PartnerUpdate 는 UUID/date 필드 없음).
    partner = await partner_service.update_partner(
        partner_id=partner_id,
        user_id=current_user["id"],
        data=data.model_dump(exclude_none=True, mode="json"),
    )
    if not partner:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Partner not found"
        )
    return {"data": partner}


@router.delete("/{partner_id}", status_code=204)
async def delete_partner(
    partner_id: UUID,
    current_user: dict = Depends(get_current_user),
):
    """거래처 삭제"""
    deleted = await partner_service.delete_partner(
        partner_id=partner_id,
        user_id=current_user["id"],
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Partner not found"
        )


@router.get(
    "/{partner_id}/stats",
    response_model=SuccessResponse[PartnerStats],
)
async def get_partner_stats(
    partner_id: UUID,
    current_user: dict = Depends(get_current_user),
):
    """거래처 거래 통계 조회.

    응답:
      - total_orders:         이 거래처와의 주문 총 건수 (CANCELLED 제외)
      - total_amount:         주문 총액 합계
      - last_order_date:      가장 최근 주문 일자 (YYYY-MM-DD)
      - active_subscriptions: 이 거래처와의 ACTIVE 정기배송 개수
    """
    stats = await partner_service.get_stats(
        partner_id=partner_id,
        user_id=current_user["id"],
    )
    return {"data": stats}
