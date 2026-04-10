import asyncio
import math
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from app.core.supabase import get_supabase_client
from app.schemas.common import PaginationMeta


class ProductService:
    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = get_supabase_client()
        return self._client

    @property
    def table(self):
        return self.client.table("products")

    async def list_products(
        self,
        *,
        seller_id: Optional[UUID] = None,
        category: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[dict], PaginationMeta]:
        query = self.table.select("*", count="exact").is_("deleted_at", None)

        if seller_id:
            query = query.eq("seller_id", str(seller_id))
        if category:
            query = query.eq("category", category)
        if status:
            query = query.eq("status", status)
        if search:
            query = query.ilike("name", f"%{search}%")

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

    async def get_product(self, product_id: UUID) -> Optional[dict]:
        result = await asyncio.to_thread(
            lambda: self.table.select("*")
            .eq("id", str(product_id))
            .is_("deleted_at", None)
            .execute()
        )
        return result.data[0] if result.data else None

    async def create_product(self, seller_id: UUID, data: dict) -> dict:
        payload = {**data, "seller_id": str(seller_id)}
        result = await asyncio.to_thread(lambda: self.table.insert(payload).execute())
        return result.data[0]

    async def update_product(
        self, product_id: UUID, seller_id: UUID, data: dict
    ) -> Optional[dict]:
        # 본인 소유 확인
        update_data = {k: v for k, v in data.items() if v is not None}
        if not update_data:
            return await self.get_product(product_id)

        result = await asyncio.to_thread(
            lambda: self.table.update(update_data)
            .eq("id", str(product_id))
            .eq("seller_id", str(seller_id))
            .execute()
        )
        return result.data[0] if result.data else None

    async def delete_product(self, product_id: UUID, seller_id: UUID) -> bool:
        deleted_at = datetime.now(timezone.utc).isoformat()
        result = await asyncio.to_thread(
            lambda: self.table.update({"deleted_at": deleted_at})
            .eq("id", str(product_id))
            .eq("seller_id", str(seller_id))
            .execute()
        )
        return bool(result.data)


product_service = ProductService()
