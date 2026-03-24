from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_current_user
from app.schemas.common import SuccessResponse
from app.schemas.partner import PartnerCreate, PartnerResponse, PartnerUpdate
from app.services.partner_service import partner_service

router = APIRouter(prefix="/partners", tags=["partners"])


@router.get("", response_model=SuccessResponse[list[PartnerResponse]])
async def list_partners(
    partner_status: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
):
    """내 거래처 목록 조회"""
    data, meta = await partner_service.list_partners(
        user_id=current_user["id"],
        status=partner_status,
        search=search,
        page=page,
        limit=limit,
    )
    return {"data": data, "meta": meta.model_dump()}


@router.post("", response_model=SuccessResponse[PartnerResponse], status_code=201)
async def create_partner(
    data: PartnerCreate,
    current_user: dict = Depends(get_current_user),
):
    """거래처 등록 요청"""
    partner = await partner_service.create_partner(
        user_id=current_user["id"],
        data=data.model_dump(),
    )
    return {"data": partner}


@router.patch("/{partner_id}", response_model=SuccessResponse[PartnerResponse])
async def update_partner(
    partner_id: UUID,
    data: PartnerUpdate,
    current_user: dict = Depends(get_current_user),
):
    """거래처 정보 수정 (별칭, 즐겨찾기 등)"""
    partner = await partner_service.update_partner(
        partner_id=partner_id,
        user_id=current_user["id"],
        data=data.model_dump(exclude_none=True),
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
