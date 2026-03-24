import asyncio
import math
from datetime import datetime, timezone
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

    @property
    def users(self):
        return self.client.table("users")

    async def list_partners(
        self,
        *,
        user_id: UUID,
        status: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[dict], PaginationMeta]:
        query = (
            self.table.select("*", count="exact")
            .eq("user_id", str(user_id))
            .is_("deleted_at", "null")
        )

        if status:
            query = query.eq("status", status)

        # 검색은 조인된 사용자 정보로 필터링해야 하므로 결과 후처리로 처리
        offset = (page - 1) * limit
        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)

        result = await asyncio.to_thread(lambda: query.execute())
        total = result.count or 0

        # 거래처 사용자 정보 조인
        partners = result.data
        for p in partners:
            user_result = await asyncio.to_thread(
                lambda pid=p["partner_user_id"]: self.users.select(
                    "name, company_name, role, phone"
                )
                .eq("id", pid)
                .single()
                .execute()
            )
            if user_result.data:
                p["partner_name"] = user_result.data["name"]
                p["partner_company"] = user_result.data["company_name"]
                p["partner_role"] = user_result.data["role"]
                p["partner_phone"] = user_result.data.get("phone")

        # 검색 필터링 (이름/업체명 기반)
        if search:
            search_lower = search.lower()
            partners = [
                p for p in partners
                if (p.get("partner_name") or "").lower().find(search_lower) >= 0
                or (p.get("partner_company") or "").lower().find(search_lower) >= 0
            ]

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
        deleted_at = datetime.now(timezone.utc).isoformat()
        result = await asyncio.to_thread(
            lambda: self.table.update({"deleted_at": deleted_at})
            .eq("id", str(partner_id))
            .eq("user_id", str(user_id))
            .execute()
        )
        return bool(result.data)


partner_service = PartnerService()
