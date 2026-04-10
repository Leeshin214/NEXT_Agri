import asyncio
import math
from typing import Optional
from uuid import UUID

from app.core.supabase import get_supabase_client
from app.schemas.common import PaginationMeta


class PartnerService:
    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = get_supabase_client()
        return self._client

    @property
    def table(self):
        return self.client.table("partners")

    async def list_partners(
        self,
        *,
        user_id: UUID,
        status: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[dict], PaginationMeta]:
        # 임베디드 조인으로 partner_user 정보를 한 번에 조회 (N+1 제거)
        query = (
            self.table.select(
                "*, partner_user:users!partner_user_id(name, company_name, role, phone)",
                count="exact",
            )
            .eq("user_id", str(user_id))
        )

        if status:
            query = query.eq("status", status)

        # 검색을 DB 쿼리 레벨에서 처리 (클라이언트 사이드 필터링 제거)
        # nickname 또는 거래처 이름/업체명으로 검색
        if search:
            query = query.or_(
                f"nickname.ilike.%{search}%,"
                f"partner_user.name.ilike.%{search}%,"
                f"partner_user.company_name.ilike.%{search}%"
            )

        # 페이지네이션을 DB 쿼리에서 처리
        offset = (page - 1) * limit
        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)

        result = await asyncio.to_thread(lambda: query.execute())
        total = result.count or 0

        # 조인된 partner_user 데이터를 PartnerResponse 호환 형식으로 flatten
        partners = []
        for p in result.data:
            partner_user = p.pop("partner_user", None) or {}
            p["partner_name"] = partner_user.get("name")
            p["partner_company"] = partner_user.get("company_name")
            p["partner_role"] = partner_user.get("role")
            p["partner_phone"] = partner_user.get("phone")
            partners.append(p)

        meta = PaginationMeta(
            total=total,
            page=page,
            limit=limit,
            total_pages=math.ceil(total / limit) if total > 0 else 0,
        )
        return partners, meta

    async def create_partner(self, user_id: UUID, data: dict) -> dict:
        payload = {
            **data,
            "user_id": str(user_id),
            "partner_user_id": str(data["partner_user_id"]),
            "status": "PENDING",
        }
        result = await asyncio.to_thread(lambda: self.table.insert(payload).execute())
        return result.data[0]

    async def update_partner(
        self, partner_id: UUID, user_id: UUID, data: dict
    ) -> Optional[dict]:
        update_data = {k: v for k, v in data.items() if v is not None}
        if not update_data:
            return None

        result = await asyncio.to_thread(
            lambda: self.table.update(update_data)
            .eq("id", str(partner_id))
            .eq("user_id", str(user_id))
            .execute()
        )
        return result.data[0] if result.data else None

    async def delete_partner(self, partner_id: UUID, user_id: UUID) -> bool:
        result = await asyncio.to_thread(
            lambda: self.table.delete()
            .eq("id", str(partner_id))
            .eq("user_id", str(user_id))
            .execute()
        )
        return bool(result.data)


partner_service = PartnerService()
