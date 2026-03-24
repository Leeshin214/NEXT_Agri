import asyncio
import math
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status

from app.core.supabase import get_supabase_client
from app.schemas.common import PaginationMeta


class OrderService:
    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = get_supabase_client()
        return self._client

    @property
    def orders(self):
        return self.client.table("orders")

    @property
    def items(self):
        return self.client.table("order_items")

    def _generate_order_number(self) -> str:
        now = datetime.now()
        date_str = now.strftime("%Y%m%d")
        # 간단한 시퀀스: 시분초 기반
        seq = now.strftime("%H%M%S")
        return f"ORD-{date_str}-{seq}"

    async def list_orders(
        self,
        *,
        user_id: UUID,
        role: str,
        status: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[dict], PaginationMeta]:
        query = self.orders.select("*", count="exact").is_("deleted_at", "null")

        # 역할에 따라 필터
        if role == "BUYER":
            query = query.eq("buyer_id", str(user_id))
        else:
            query = query.eq("seller_id", str(user_id))

        if status:
            query = query.eq("status", status)

        offset = (page - 1) * limit
        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)

        result = await asyncio.to_thread(lambda: query.execute())
        total = result.count or 0

        # 각 주문에 items 붙이기
        orders = result.data
        for order in orders:
            items_result = await asyncio.to_thread(
                lambda oid=order["id"]: self.items.select("*").eq("order_id", oid).execute()
            )
            order["items"] = items_result.data

        meta = PaginationMeta(
            total=total,
            page=page,
            limit=limit,
            total_pages=math.ceil(total / limit) if total > 0 else 0,
        )
        return orders, meta

    async def get_order(self, order_id: UUID) -> Optional[dict]:
        result = await asyncio.to_thread(
            lambda: self.orders.select("*")
            .eq("id", str(order_id))
            .is_("deleted_at", "null")
            .single()
            .execute()
        )
        if not result.data:
            return None

        order = result.data
        items_result = await asyncio.to_thread(
            lambda: self.items.select("*").eq("order_id", str(order_id)).execute()
        )
        order["items"] = items_result.data
        return order

    async def create_order(self, buyer_id: UUID, data: dict) -> dict:
        items_data = data.pop("items", [])

        # 총액 계산
        total = sum(item["quantity"] * item["unit_price"] for item in items_data)

        order_payload = {
            **data,
            "buyer_id": str(buyer_id),
            "seller_id": str(data["seller_id"]),
            "order_number": self._generate_order_number(),
            "total_amount": total,
            "status": "QUOTE_REQUESTED",
        }

        result = await asyncio.to_thread(
            lambda: self.orders.insert(order_payload).execute()
        )
        order = result.data[0]

        # 주문 항목 생성
        for item in items_data:
            await asyncio.to_thread(
                lambda i=item: self.items.insert(
                    {
                        "order_id": order["id"],
                        "product_id": str(i["product_id"]),
                        "quantity": i["quantity"],
                        "unit_price": i["unit_price"],
                        "subtotal": i["quantity"] * i["unit_price"],
                        "notes": i.get("notes"),
                    }
                ).execute()
            )

        return await self.get_order(order["id"])

    async def update_status(
        self, order_id: UUID, user_id: UUID, new_status: str
    ) -> Optional[dict]:
        # 주문 당사자(seller 또는 buyer) 확인 후 업데이트
        user_id_str = str(user_id)
        result = await asyncio.to_thread(
            lambda: self.orders.update({"status": new_status})
            .eq("id", str(order_id))
            .or_(f"seller_id.eq.{user_id_str},buyer_id.eq.{user_id_str}")
            .execute()
        )
        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Order not found or you do not have permission to update this order",
            )
        return await self.get_order(order_id)


order_service = OrderService()
