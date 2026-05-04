import asyncio
import logging
from collections import Counter
from typing import Any, Optional
from uuid import UUID

from app.core.supabase import get_supabase_client


logger = logging.getLogger(__name__)


# 허용된 message_type 값 (DB CHECK 제약과 동기화)
# 주의: 마이그레이션 20260429000001_create_delivery_date_change_history.sql 의
# messages.message_type CHECK 제약과 1:1 동기화되어야 한다.
ALLOWED_MESSAGE_TYPES = {
    "TEXT",
    "SYSTEM",
    "COUNTER_OFFER",
    "OFFER_ACCEPTED",
    "OFFER_REJECTED",
    "ORDER_STATUS",
    "ORDER_CANCELLED",
    # 납품일 변경 흐름 (2026-04-29 추가)
    "DELIVERY_DATE_CHANGE",
    "DELIVERY_DATE_ACCEPTED",
    "DELIVERY_DATE_REJECTED",
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
        self,
        user_id: UUID,
        role: str,
        partner_user_id: UUID,
        order_id: Optional[UUID] = None,
        inquiry_product_id: Optional[UUID] = None,
    ) -> dict:
        """채팅방을 찾거나 새로 생성한다.

        - inquiry_product_id 가 전달되고 새 채팅방이 만들어진 경우(즉, 같은 buyer-seller-order
          조합의 기존 방이 없는 경우) 자동으로 시스템 메시지 1건을 발송하고
          그 메시지의 metadata 에 {kind: 'product_inquiry', inquiry_product_id} 를 저장한다.
          기존 방을 그대로 반환하는 경우엔 자동 메시지 발송 X — 호출처가 별도로 처리.
        - inquiry_product_id 가 None 이면 기존 동작 그대로 (다른 흐름 영향 없음).
        """
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
            # 기존 방이 있으면 그대로 반환 — inquiry_product_id 자동 메시지 발송 안 함
            # (호출처가 같은 상품 문의를 다시 보내고 싶으면 직접 send_message 호출)
            return result.data[0]

        # 새 채팅방 생성
        payload = {"seller_id": seller_id, "buyer_id": buyer_id}
        if order_id:
            payload["order_id"] = str(order_id)
        result = await asyncio.to_thread(lambda: self.rooms.insert(payload).execute())
        new_room = result.data[0]

        # inquiry_product_id 가 있으면 자동으로 시스템 메시지 발송 (B.2, 2026-05-04)
        # 메시지 발송 실패해도 채팅방 자체는 정상 생성된 상태 — best-effort 로그만.
        if inquiry_product_id and new_room:
            try:
                await self._send_product_inquiry_system_message(
                    room_id=new_room["id"],
                    sender_id=user_id,
                    inquiry_product_id=inquiry_product_id,
                )
            except Exception as e:
                logger.error(
                    "[chat_service.get_or_create_room] product inquiry system message 실패 "
                    "(무시): room_id=%s product_id=%s error=%s: %s",
                    new_room.get("id"),
                    inquiry_product_id,
                    type(e).__name__,
                    e,
                )

        return new_room

    async def _send_product_inquiry_system_message(
        self,
        *,
        room_id: UUID | str,
        sender_id: UUID | str,
        inquiry_product_id: UUID | str,
    ) -> Optional[dict]:
        """상품 문의로 채팅방이 새로 만들어졌을 때 발송하는 시스템 메시지.

        - 메시지 본문에는 상품명/단가/단위/카테고리/원산지 정보를 자연어로 포함.
        - metadata 에 {kind: 'product_inquiry', inquiry_product_id} 를 저장 — 프론트가
          채팅방 진입 시 첫 메시지의 metadata.inquiry_product_id 로 미니카드 렌더 가능.
        - 상품 정보 조회 실패 시 fallback 으로 product_id 만 metadata 에 저장하고
          본문은 '[상품 문의]' 로 단순화.
        """
        product_id_str = str(inquiry_product_id)

        # 상품 정보 조회 (best-effort) — 실패해도 metadata 만은 저장
        product_info: dict = {}
        try:
            product_result = await asyncio.to_thread(
                lambda: self.client.table("products")
                .select("id, name, category, unit, price_per_unit, origin")
                .eq("id", product_id_str)
                .is_("deleted_at", None)
                .limit(1)
                .execute()
            )
            if product_result.data:
                product_info = product_result.data[0] or {}
        except Exception as e:
            logger.warning(
                "[chat_service._send_product_inquiry_system_message] "
                "product 조회 실패 (메타데이터만 저장): %s: %s",
                type(e).__name__,
                e,
            )

        # 본문 작성
        if product_info:
            name = product_info.get("name") or "-"
            unit = product_info.get("unit") or ""
            price = product_info.get("price_per_unit")
            origin = product_info.get("origin")
            price_text = (
                f"{int(price):,}원/{unit}" if isinstance(price, (int, float)) and price is not None
                else "-"
            )
            origin_text = f" / 원산지: {origin}" if origin else ""
            content = (
                f"[상품 문의] 상품: {name} / 단가: {price_text}{origin_text}"
            )
        else:
            content = "[상품 문의]"

        metadata = {
            "kind": "product_inquiry",
            "inquiry_product_id": product_id_str,
        }

        return await self.send_event_message(
            room_id=room_id,
            sender_id=sender_id,
            message_type="SYSTEM",
            content=content,
            metadata=metadata,
            is_read=False,  # 상대방에게 미읽음으로 노출
        )

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

        # 알림 emit — 채팅방 상대방에게 NEW_MESSAGE
        # 실패해도 메시지 송수신 자체는 막지 않도록 try/except 로 격리.
        try:
            await self._emit_new_message_notification(
                room_id=room_id, sender_id=sender_id, content=content
            )
        except Exception as e:
            logger.error(
                "[chat_service.send_message] notification emit 실패 (무시): "
                "room_id=%s sender_id=%s error=%s: %s",
                room_id,
                sender_id,
                type(e).__name__,
                e,
            )

        return message

    async def _emit_new_message_notification(
        self,
        *,
        room_id: UUID | str,
        sender_id: UUID | str,
        content: str,
    ) -> None:
        """채팅방 상대방에게 NEW_MESSAGE 알림 emit.

        - chat_rooms 에서 (seller_id, buyer_id) 조회 후 sender_id 가 아닌 쪽이 수신자.
        - 자기 자신에게는 보내지 않음 (sender_id == receiver_id 면 skip).
        - body 는 메시지 본문 80자 truncate, title 은 발신자 이름.
        - link_url 은 수신자 role 기준 (`/buyer/chat?room_id=...` or `/seller/chat?...`).

        notification_service 는 chat_service 를 import 하지 않으므로 순환 안전.
        notification_service 를 함수 내부에서 import 하여 모듈 로드 순서 의존성도 회피.
        """
        from app.services.notification_service import notification_service

        room_id_str = str(room_id)
        sender_id_str = str(sender_id)

        # 1) 채팅방 조회
        room_result = await asyncio.to_thread(
            lambda: self.rooms.select("id, seller_id, buyer_id")
            .eq("id", room_id_str)
            .single()
            .execute()
        )
        room = room_result.data
        if not room:
            return

        seller_id = str(room.get("seller_id") or "")
        buyer_id = str(room.get("buyer_id") or "")

        # 2) 수신자 결정 (sender 가 아닌 쪽)
        if sender_id_str == seller_id:
            receiver_id = buyer_id
            receiver_role = "BUYER"
        elif sender_id_str == buyer_id:
            receiver_id = seller_id
            receiver_role = "SELLER"
        else:
            # 발신자가 채팅방 참여자가 아닌 비정상 케이스 — skip
            return

        # 3) 자기 자신 skip
        if not receiver_id or receiver_id == sender_id_str:
            return

        # 4) 발신자 이름 조회 (title 용)
        sender_name = "상대방"
        try:
            sender_result = await asyncio.to_thread(
                lambda: self.client.table("users")
                .select("name, company_name")
                .eq("id", sender_id_str)
                .single()
                .execute()
            )
            sender_data = sender_result.data or {}
            sender_name = (
                sender_data.get("name")
                or sender_data.get("company_name")
                or "상대방"
            )
        except Exception as e:
            logger.error(
                "[chat_service._emit_new_message_notification] "
                "sender 이름 조회 실패 (무시): %s: %s",
                type(e).__name__,
                e,
            )

        # 5) link_url — 수신자 역할 기준 채팅 페이지
        prefix = "buyer" if receiver_role == "BUYER" else "seller"
        link_url = f"/{prefix}/chat?room_id={room_id_str}"

        # 6) body — 메시지 80자 truncate (notification_service.emit 도 추가 truncate 안전망)
        body = content if len(content) <= 80 else content[:77] + "..."

        await notification_service.emit(
            user_id=receiver_id,
            notification_type="NEW_MESSAGE",
            title=sender_name,
            body=body,
            link_url=link_url,
            room_id=room_id_str,
        )

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
