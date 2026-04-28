import asyncio
from collections import Counter
from typing import Any, Optional
from uuid import UUID

from app.core.supabase import get_supabase_client


# 허용된 message_type 값 (DB CHECK 제약과 동기화)
ALLOWED_MESSAGE_TYPES = {
    "TEXT",
    "SYSTEM",
    "COUNTER_OFFER",
    "OFFER_ACCEPTED",
    "OFFER_REJECTED",
    "ORDER_STATUS",
    "ORDER_CANCELLED",
}


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

        # 상대방 user 가 soft-deleted 인 방은 list 에서 제외 (정책: 가장 단순한 옵션)
        # 임베디드 조인은 deleted_at 자동 필터링하지 않으므로 별도 조회로 검증.
        partner_id_key = "buyer_id" if role == "SELLER" else "seller_id"
        partner_ids = list({room[partner_id_key] for room in rooms if room.get(partner_id_key)})
        active_partner_ids: set[str] = set()
        if partner_ids:
            partner_status_result = await asyncio.to_thread(
                lambda: self.client.table("users")
                .select("id")
                .in_("id", partner_ids)
                .is_("deleted_at", None)
                .execute()
            )
            active_partner_ids = {u["id"] for u in (partner_status_result.data or [])}
        rooms = [r for r in rooms if r.get(partner_id_key) in active_partner_ids]
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
        # soft-deleted 메시지 제외 (.is_("deleted_at", None))
        query = (
            self.messages.select("*")
            .eq("room_id", str(room_id))
            .is_("deleted_at", None)
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
        # 일반 사용자 메시지 — message_type='TEXT' (DB DEFAULT 적용)
        msg_result = await asyncio.to_thread(
            lambda: self.messages.insert(
                {
                    "room_id": str(room_id),
                    "sender_id": str(sender_id),
                    "content": content,
                    "message_type": "TEXT",
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
        # soft-deleted 메시지는 읽음 처리 대상에서 제외
        await asyncio.to_thread(
            lambda: self.messages.update({"is_read": True})
            .eq("room_id", str(room_id))
            .neq("sender_id", str(user_id))
            .eq("is_read", False)
            .is_("deleted_at", None)
            .execute()
        )

    async def send_event_message(
        self,
        room_id: UUID | str,
        sender_id: UUID | str,
        message_type: str,
        content: str,
        metadata: Optional[dict[str, Any]] = None,
        is_read: bool = True,
    ) -> dict:
        """일반화된 이벤트 메시지 INSERT (시스템/협상가/주문상태 등).

        send_message 와 달리 message_type 을 명시할 수 있고 metadata(JSONB) 를 함께 저장한다.
        chat_rooms.last_message / last_message_at 자동 갱신.

        - SYSTEM 메시지의 경우 호출자가 content 앞에 [SYSTEM] prefix 를 붙여 호출하거나,
          이 함수가 자동으로 붙인다 (message_type='SYSTEM' 일 때).
        - 그 외 message_type 은 prefix 자동 추가 없음 — 호출자가 표시 형식을 결정.

        반환: insert 된 message dict (실패 시 {})
        """
        if message_type not in ALLOWED_MESSAGE_TYPES:
            print(f"[chat_service] 알 수 없는 message_type={message_type!r} → TEXT 로 fallback")
            message_type = "TEXT"

        # SYSTEM 메시지는 [SYSTEM] prefix 자동 부착 (기존 동작 유지)
        if message_type == "SYSTEM" and not content.startswith("[SYSTEM]"):
            content = f"[SYSTEM] {content}"

        insert_payload: dict[str, Any] = {
            "room_id": str(room_id),
            "sender_id": str(sender_id),
            "content": content,
            "message_type": message_type,
            "is_read": is_read,
        }
        if metadata is not None:
            insert_payload["metadata"] = metadata

        msg_result = await asyncio.to_thread(
            lambda: self.messages.insert(insert_payload).execute()
        )
        if not msg_result.data:
            return {}
        message = msg_result.data[0]

        # 채팅방 last_message 업데이트 (모든 이벤트 메시지가 마지막 메시지로 표시됨)
        await asyncio.to_thread(
            lambda: self.rooms.update(
                {"last_message": content, "last_message_at": message["created_at"]}
            ).eq("id", str(room_id)).execute()
        )
        return message

    async def send_system_message(
        self, room_id: UUID | str, content: str, sender_id: UUID | str
    ) -> dict:
        """시스템 메시지를 messages 테이블에 INSERT 한다 (send_event_message 위임).

        messages.sender_id 가 NOT NULL 제약이므로 fallback sender_id 가 반드시 필요하다.
        호출처(chat_ws.py)는 chat_room.seller_id 를 fallback 으로 전달한다.

        반환: insert 된 message dict (id, room_id, sender_id, content, is_read, created_at, deleted_at, message_type, metadata)
        """
        return await self.send_event_message(
            room_id=room_id,
            sender_id=sender_id,
            message_type="SYSTEM",
            content=content,
            is_read=True,
        )


chat_service = ChatService()
