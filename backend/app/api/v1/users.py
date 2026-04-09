from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.supabase import get_supabase_client
from app.dependencies import get_current_user
from app.schemas.common import SuccessResponse
from app.schemas.user import UserPublicProfile, UserResponse, UserUpdate
from app.services.user_service import user_service

router = APIRouter(prefix="/users", tags=["users"])

# 역할 반전 매핑 (라우터 레벨 검증용)
_OPPOSITE_ROLE = {"SELLER": "BUYER", "BUYER": "SELLER"}


@router.get("/me", response_model=SuccessResponse[UserResponse])
async def get_me(current_user: dict = Depends(get_current_user)):
    """현재 로그인된 사용자 정보"""
    return {"data": current_user}


@router.patch("/me", response_model=SuccessResponse[UserResponse])
async def update_me(
    data: UserUpdate,
    current_user: dict = Depends(get_current_user),
):
    """내 프로필 수정"""
    update_data = data.model_dump(exclude_none=True)
    if not update_data:
        return {"data": current_user}

    client = get_supabase_client()
    result = (
        client.table("users")
        .update(update_data)
        .eq("id", current_user["id"])
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update user",
        )

    return {"data": result.data[0]}


_ALLOWED_SEARCH_ROLES = {"SELLER", "BUYER"}


@router.get("/search", response_model=SuccessResponse[list[UserPublicProfile]])
async def search_users(
    search: Optional[str] = None,
    role: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
):
    """
    회원 검색 (프로필 탐색).
    - role 파라미터를 명시하면 해당 역할(SELLER 또는 BUYER)로 검색.
    - role 파라미터가 없으면 요청자의 반대 역할로 fallback.
    - ADMIN 등 허용되지 않은 role 값은 400으로 거부.
    검색어는 이름·업체명·이메일에 대해 OR 조건으로 적용.
    """
    requester_role = current_user.get("role", "")
    if requester_role not in _OPPOSITE_ROLE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="검색 권한이 없습니다.",
        )

    if role is not None:
        if role not in _ALLOWED_SEARCH_ROLES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"허용된 role 값은 SELLER 또는 BUYER입니다. 전달된 값: {role}",
            )
        target_role = role
    else:
        target_role = _OPPOSITE_ROLE[requester_role]

    data, meta = await user_service.search_users(
        target_role=target_role,
        search=search,
        page=page,
        limit=limit,
    )
    return {"data": data, "meta": meta.model_dump()}


@router.get("/{user_id}/profile", response_model=SuccessResponse[UserPublicProfile])
async def get_user_profile(
    user_id: UUID,
    current_user: dict = Depends(get_current_user),
):
    """
    개별 공개 프로필 조회.
    인증된 사용자라면 역할 무관하게 조회 가능.
    """
    profile = await user_service.get_user_profile(user_id)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return {"data": profile}
