from fastapi import APIRouter, Depends, HTTPException, status

from app.core.supabase import get_supabase_client
from app.dependencies import get_current_user
from app.schemas.common import SuccessResponse
from app.schemas.user import UserResponse, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


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
