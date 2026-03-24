import asyncio
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from app.core.supabase import get_supabase_client


class CalendarService:
    def __init__(self):
        self.client = get_supabase_client()
        self.table = self.client.table("calendar_events")

    async def list_events(
        self,
        *,
        user_id: UUID,
        year: int,
        month: int,
    ) -> list[dict]:
        # 해당 월의 이벤트 조회
        start_date = f"{year}-{month:02d}-01"
        if month == 12:
            end_date = f"{year + 1}-01-01"
        else:
            end_date = f"{year}-{month + 1:02d}-01"

        result = await asyncio.to_thread(
            lambda: self.table.select("*")
            .eq("user_id", str(user_id))
            .is_("deleted_at", "null")
            .gte("event_date", start_date)
            .lt("event_date", end_date)
            .order("event_date")
            .execute()
        )
        return result.data

    async def create_event(self, user_id: UUID, data: dict) -> dict:
        payload = {**data, "user_id": str(user_id)}
        # date/time 객체를 문자열로 변환
        for key in ("event_date", "start_time", "end_time"):
            if key in payload and payload[key] is not None:
                payload[key] = str(payload[key])
        if "order_id" in payload and payload["order_id"] is not None:
            payload["order_id"] = str(payload["order_id"])

        result = await asyncio.to_thread(lambda: self.table.insert(payload).execute())
        return result.data[0]

    async def update_event(
        self, event_id: UUID, user_id: UUID, data: dict
    ) -> Optional[dict]:
        update_data = {k: v for k, v in data.items() if v is not None}
        for key in ("event_date", "start_time", "end_time"):
            if key in update_data:
                update_data[key] = str(update_data[key])

        if not update_data:
            return None

        result = await asyncio.to_thread(
            lambda: self.table.update(update_data)
            .eq("id", str(event_id))
            .eq("user_id", str(user_id))
            .execute()
        )
        return result.data[0] if result.data else None

    async def delete_event(self, event_id: UUID, user_id: UUID) -> bool:
        deleted_at = datetime.now(timezone.utc).isoformat()
        result = await asyncio.to_thread(
            lambda: self.table.update({"deleted_at": deleted_at})
            .eq("id", str(event_id))
            .eq("user_id", str(user_id))
            .execute()
        )
        return bool(result.data)


calendar_service = CalendarService()
