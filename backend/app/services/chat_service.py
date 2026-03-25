import asyncio
from collections import Counter
from typing import Optional
from uuid import UUID

from app.core.supabase import get_supabase_client


class ChatService:
    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = get_supabase_client()
        return self._client

    @property
    def rooms(self):
        return self.client.table("chat_rooms")

    @property
    def messages(self):
        return self.client.table("messages")

    async def list_rooms(self, user_id: UUID, role: str) -> list[dict]:
        # 임베디드 조인으로 seller/buyer 정보를 한 번에 조회 (N+1 제거)
        if role == "SELLER":
            result = await asyncio.to_thread(
                lambda: self.rooms.select(
                    "*, seller:users!seller_id(name, company_name),"
                    " buyer:users!buyer_id(name, company_name)"
                )
                .eq("seller_id", str(user_id))
                .order("last_message_at", desc=True, nullsfirst=False)
                .execute()
            )
        else:
            result = await asyncio.to_thread(
                lambda: self.rooms.select(
                    "*, seller:users!seller_id(name, company_name),"
                    " buyer:users!buyer_id(name, company_name)"
                )
                .eq("buyer_id", str(user_id))
                .order("last_message_at", desc=True, nullsfirst=False)
                .execute()
            )

        rooms = result.data
        if not rooms:
            return []

        # 조인된 seller/buyer 데이터를 partner_name/partner_company 로 flatten
        for room in rooms:
            seller = room.pop("seller", None) or {}
            buyer = room.pop("buyer", None) or {}
            if role == "SELLER":
                room["partner_name"] = buyer.get("name")
                room["partner_company"] = buyer.get("company_name")
            else:
                room["partner_name"] = seller.get("name")
                room["partner_company"] = seller.get("company_name")

        # 모든 방의 미읽음 수를 한 번에 조회 (N+1 제거)
        room_ids = [room["id"] for room in rooms]
        unread_result = await asyncio.to_thread(
            lambda: self.messages.select("room_id")
            .eq("is_read", False)
            .neq("sender_id", str(user_id))
            .in_("room_id", room_ids)
            .execute()
        )

        # Python에서 room_id별 count 집계
        unread_counts: Counter = Counter(
            msg["room_id"] for msg in (unread_result.data or [])
        )

        for room in rooms:
            room["unread_count"] = unread_counts.get(room["id"], 0)

        return rooms

    async def get_or_create_room(
        self, user_id: UUID, role: str, partner_user_id: UUID, order_id: Optional[UUID] = None
    ) -> dict:
        if role == "SELLER":
            seller_id, buyer_id = str(user_id), str(partner_user_id)
        else:
            seller_id, buyer_id = str(partner_user_id), str(user_id)

        # 기존 채팅방 검색
        query = (
            self.rooms.select("*")
            .eq("seller_id", seller_id)
            .eq("buyer_id", buyer_id)
        )
        if order_id:
            query = query.eq("order_id", str(order_id))

        result = await asyncio.to_thread(lambda: query.execute())
        if result.data:
            return result.data[0]

        # 새 채팅방 생성
        payload = {"seller_id": seller_id, "buyer_id": buyer_id}
        if order_id:
            payload["order_id"] = str(order_id)
        result = await asyncio.to_thread(lambda: self.rooms.insert(payload).execute())
        return result.data[0]

    async def list_messages(
        self, room_id: UUID, limit: int = 50, before: Optional[str] = None
    ) -> list[dict]:
        query = (
            self.messages.select("*")
            .eq("room_id", str(room_id))
            .order("created_at", desc=True)
            .limit(limit)
        )
        if before:
            query = query.lt("created_at", before)

        result = await asyncio.to_thread(lambda: query.execute())
        return list(reversed(result.data))

    async def send_message(
        self, room_id: UUID, sender_id: UUID, content: str
    ) -> dict:
        # 메시지 저장
        msg_result = await asyncio.to_thread(
            lambda: self.messages.insert(
                {
                    "room_id": str(room_id),
                    "sender_id": str(sender_id),
                    "content": content,
                }
            ).execute()
        )
        message = msg_result.data[0]

        # 채팅방 last_message 업데이트
        await asyncio.to_thread(
            lambda: self.rooms.update(
                {"last_message": content, "last_message_at": message["created_at"]}
            ).eq("id", str(room_id)).execute()
        )

        return message

    async def mark_as_read(self, room_id: UUID, user_id: UUID) -> None:
        await asyncio.to_thread(
            lambda: self.messages.update({"is_read": True})
            .eq("room_id", str(room_id))
            .neq("sender_id", str(user_id))
            .eq("is_read", False)
            .execute()
        )


chat_service = ChatService()
