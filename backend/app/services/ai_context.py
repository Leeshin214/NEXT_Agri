import asyncio
from datetime import date

from app.core.supabase import get_supabase_client


class AIContextBuilder:
    def __init__(self):
        self._client = None  # 즉시 생성하지 않음

    @property
    def client(self):
        if self._client is None:
            self._client = get_supabase_client()
        return self._client

    async def build_seller_context(self, user_id: str) -> str:
        """판매자 컨텍스트: 오늘 출하, 재고 부족, 미응답 견적"""
        today_str = date.today().isoformat()

        # 오늘 출하 일정
        shipments = await asyncio.to_thread(
            lambda: self.client.table("calendar_events")
            .select("title, event_type")
            .eq("user_id", user_id)
            .eq("event_type", "SHIPMENT")
            .eq("event_date", today_str)
            .execute()
        )
        shipment_list = shipments.data or []

        # 재고 부족 품목
        low_stock = await asyncio.to_thread(
            lambda: self.client.table("products")
            .select("name, stock_quantity, unit, status")
            .eq("seller_id", user_id)
            .in_("status", ["LOW_STOCK", "OUT_OF_STOCK"])
            .is_("deleted_at", "null")
            .execute()
        )
        low_items = low_stock.data or []

        # 미응답 견적
        pending = await asyncio.to_thread(
            lambda: self.client.table("orders")
            .select("id", count="exact")
            .eq("seller_id", user_id)
            .eq("status", "QUOTE_REQUESTED")
            .execute()
        )
        pending_count = pending.count or 0

        shipment_lines = "\n".join(
            [f"- {s['title']}" for s in shipment_list]
        ) if shipment_list else "- 없음"

        low_stock_lines = "\n".join(
            [f"- {p['name']}: {p['stock_quantity']}{p['unit']} ({p['status']})" for p in low_items]
        ) if low_items else "- 없음"

        return (
            f"오늘 출하 예정: {len(shipment_list)}건\n"
            f"{shipment_lines}\n\n"
            f"재고 부족 품목: {len(low_items)}개\n"
            f"{low_stock_lines}\n\n"
            f"미응답 견적 요청: {pending_count}건"
        )

    async def build_buyer_context(self, user_id: str) -> str:
        """구매자 컨텍스트: 진행중 주문, 오늘 납품, 대기 견적"""
        today_str = date.today().isoformat()

        # 진행중 주문
        active = await asyncio.to_thread(
            lambda: self.client.table("orders")
            .select("id", count="exact")
            .eq("buyer_id", user_id)
            .in_("status", ["CONFIRMED", "PREPARING", "SHIPPING"])
            .execute()
        )
        active_count = active.count or 0

        # 오늘 납품 예정
        deliveries = await asyncio.to_thread(
            lambda: self.client.table("calendar_events")
            .select("title, event_type")
            .eq("user_id", user_id)
            .eq("event_type", "DELIVERY")
            .eq("event_date", today_str)
            .execute()
        )
        delivery_list = deliveries.data or []

        # 대기 견적
        pending = await asyncio.to_thread(
            lambda: self.client.table("orders")
            .select("id", count="exact")
            .eq("buyer_id", user_id)
            .in_("status", ["QUOTE_REQUESTED", "NEGOTIATING"])
            .execute()
        )
        pending_count = pending.count or 0

        delivery_lines = "\n".join(
            [f"- {d['title']}" for d in delivery_list]
        ) if delivery_list else "- 없음"

        return (
            f"진행중 주문: {active_count}건\n\n"
            f"오늘 납품 예정: {len(delivery_list)}건\n"
            f"{delivery_lines}\n\n"
            f"대기 중 견적: {pending_count}건"
        )


ai_context_builder = AIContextBuilder()
