import asyncio
import math
from typing import Optional
from uuid import UUID

from app.core.supabase import get_supabase_client
from app.schemas.common import PaginationMeta

class UserService:
    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = get_supabase_client()
        return self._client

    @property
    def table(self):
        return self.client.table("users")

    async def search_users(
        self,
        *,
        target_role: str,
        search: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[dict], PaginationMeta]:
        """
        target_role에 해당하는 사용자를 검색한다.
        역할 반전 및 유효성 검증은 라우터(users.py)에서 처리한다.
        검색어는 name, company_name, email에 대해 OR ilike로 적용.
        supabase_uid는 select 컬럼에서 제외.
        """
        # supabase_uid를 제외한 공개 컬럼만 선택
        columns = "id,email,name,role,company_name,phone,profile_image,is_active,created_at,updated_at,deleted_at"

        query = (
            self.table
            .select(columns, count="exact")
            .eq("role", target_role)
            .eq("is_active", True)
            .is_("deleted_at", "null")
        )

        if search:
            # Supabase Python 클라이언트의 or_ 필터: "col1.ilike.%val%,col2.ilike.%val%"
            escaped = search.replace("%", r"\%").replace("_", r"\_")
            pattern = f"%{escaped}%"
            query = query.or_(
                f"name.ilike.{pattern},"
                f"company_name.ilike.{pattern},"
                f"email.ilike.{pattern}"
            )

        offset = (page - 1) * limit
        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)

        result = await asyncio.to_thread(lambda: query.execute())
        total = result.count or 0

        meta = PaginationMeta(
            total=total,
            page=page,
            limit=limit,
            total_pages=math.ceil(total / limit) if total > 0 else 0,
        )
        return result.data, meta

    async def get_user_profile(self, user_id: UUID) -> Optional[dict]:
        """
        단일 사용자 공개 프로필 조회.
        is_active=True, deleted_at IS NULL 조건 적용.
        supabase_uid는 반환하지 않음.
        """
        columns = "id,email,name,role,company_name,phone,profile_image,is_active,created_at,updated_at,deleted_at"

        result = await asyncio.to_thread(
            lambda: self.table
            .select(columns)
            .eq("id", str(user_id))
            .eq("is_active", True)
            .is_("deleted_at", "null")
            .single()
            .execute()
        )
        return result.data


user_service = UserService()
