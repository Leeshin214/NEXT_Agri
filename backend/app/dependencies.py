import asyncio
from typing import Callable, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import verify_supabase_jwt
from app.core.supabase import get_supabase_client

security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    """JWT에서 현재 사용자 정보를 조회한다."""
    if credentials is None:
        print("[AUTH] credentials is None → 401 (토큰 미전송)")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증이 필요합니다.",
        )
    print(f"[AUTH] token received: {credentials.credentials[:30]}...")
    payload = await verify_supabase_jwt(credentials.credentials)
    supabase_uid = payload.get("sub")

    if not supabase_uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    client = get_supabase_client()
    result = await asyncio.to_thread(
        lambda: client.table("users")
        .select("*")
        .eq("supabase_uid", supabase_uid)
        .single()
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return result.data


def require_role(role: str) -> Callable:
    """특정 역할만 접근 가능하도록 하는 의존성 함수"""

    async def role_checker(
        current_user: dict = Depends(get_current_user),
    ) -> dict:
        if current_user.get("role") != role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required role: {role}",
            )
        return current_user

    return role_checker


# 역할별 의존성 바로가기
require_seller = require_role("SELLER")
require_buyer = require_role("BUYER")
require_admin = require_role("ADMIN")
