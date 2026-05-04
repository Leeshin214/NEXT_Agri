import asyncio
import logging
import math
import random
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException, status
from postgrest.exceptions import APIError as PostgrestAPIError

from app.core.supabase import get_supabase_client
from app.schemas.common import PaginationMeta
# chat_service 는 order_service 를 import 하지 않으므로 순환 import 안전 (Option A)
from app.services.chat_service import chat_service
# notification_service 도 단방향 의존 — 알림 INSERT 만 수행 (역참조 없음)
from app.services.notification_service import notification_service
from app.websocket.connection_manager import manager as ws_manager


logger = logging.getLogger(__name__)


# ===========================================
# 주문 상태 전이 가드 (도메인 규칙)
# ===========================================
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "QUOTE_REQUESTED": {"NEGOTIATING", "CONFIRMED", "CANCELLED"},
    "NEGOTIATING": {"CONFIRMED", "CANCELLED", "QUOTE_REQUESTED"},
    "CONFIRMED": {"PREPARING", "CANCELLED"},
    "PREPARING": {"SHIPPING", "CANCELLED"},
    "SHIPPING": {"COMPLETED"},
    "COMPLETED": set(),
    "CANCELLED": set(),
}

# 상태 전환별 허용 역할 — (current_status, new_status) 페어별 화이트리스트
# 값이 비어있는 set() = 어느 역할도 불가, None 가드 = 모든 역할 허용 (set 명시로 표현)
# 정책 (2026-04-27 완화):
#   QUOTE_REQUESTED → CONFIRMED  : BUYER + SELLER (판매자 즉시 수락 / 구매자 자체 확정)
#   NEGOTIATING     → CONFIRMED  : BUYER + SELLER
#   CONFIRMED       → PREPARING  : SELLER 전용 (출하 책임)
#   PREPARING       → SHIPPING   : SELLER 전용
#   SHIPPING        → COMPLETED  : BUYER + SELLER (수령 확인 / 직접 전달)
#   * → CANCELLED                : BUYER + SELLER
#   NEGOTIATING → QUOTE_REQUESTED: BUYER + SELLER (협상 롤백)
#   * → NEGOTIATING              : BUYER + SELLER (협상 진입)
TRANSITION_ROLE_GUARD: dict[tuple[str, str], set[str]] = {
    ("QUOTE_REQUESTED", "CONFIRMED"):       {"BUYER", "SELLER"},
    ("QUOTE_REQUESTED", "NEGOTIATING"):     {"BUYER", "SELLER"},
    ("QUOTE_REQUESTED", "CANCELLED"):       {"BUYER", "SELLER"},
    ("NEGOTIATING",     "CONFIRMED"):       {"BUYER", "SELLER"},
    ("NEGOTIATING",     "QUOTE_REQUESTED"): {"BUYER", "SELLER"},
    ("NEGOTIATING",     "CANCELLED"):       {"BUYER", "SELLER"},
    ("CONFIRMED",       "PREPARING"):       {"SELLER"},
    ("CONFIRMED",       "CANCELLED"):       {"BUYER", "SELLER"},
    ("PREPARING",       "SHIPPING"):        {"SELLER"},
    ("PREPARING",       "CANCELLED"):       {"BUYER", "SELLER"},
    ("SHIPPING",        "COMPLETED"):       {"BUYER", "SELLER"},
}

ORDER_STATUS_CANCELLED = "CANCELLED"
ORDER_STATUS_LABELS: dict[str, str] = {
    "QUOTE_REQUESTED": "견적 요청",
    "NEGOTIATING": "협상 중",
    "CONFIRMED": "주문 확정",
    "PREPARING": "출하 준비",
    "SHIPPING": "배송 중",
    "COMPLETED": "완료",
    "CANCELLED": "취소",
}


# ===========================================
# Supabase select 임베딩 (orders join 응답용)
# ===========================================
# users!buyer_id / users!seller_id : column-alias FK embedding (FK 이름 명시 불필요)
# products(...)                    : order_items.product_id FK 자동 추론
ORDER_SELECT_WITH_JOINS = (
    "*,"
    "items:order_items(*,product:products(name,unit,category)),"
    "buyer:users!buyer_id(name,company_name),"
    "seller:users!seller_id(name,company_name)"
)


def _flatten_order_row(row: dict) -> dict:
    """PostgREST 임베딩 응답을 OrderResponse 평탄 구조로 변환.

    - row["buyer"] / row["seller"] → buyer_name/buyer_company/seller_name/seller_company
    - row["items"][i]["product"] → product_name/product_unit/product_category
    삭제된 사용자/상품으로 임베딩이 None 인 경우 빈 dict 처리해 None 으로 채움.
    """
    buyer = row.pop("buyer", None) or {}
    seller = row.pop("seller", None) or {}
    row["buyer_name"] = buyer.get("name")
    row["buyer_company"] = buyer.get("company_name")
    row["seller_name"] = seller.get("name")
    row["seller_company"] = seller.get("company_name")

    items = row.get("items") or []
    flat_items = []
    for item in items:
        product = item.pop("product", None) or {}
        item["product_name"] = product.get("name")
        item["product_unit"] = product.get("unit")
        item["product_category"] = product.get("category")
        flat_items.append(item)
    row["items"] = flat_items
    return row


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

    @property
    def negotiations(self):
        return self.client.table("negotiation_history")

    @property
    def delivery_date_changes(self):
        return self.client.table("delivery_date_change_history")

    @property
    def calendar_events(self):
        return self.client.table("calendar_events")

    def _generate_order_number(self) -> str:
        # ORD-{YYYYMMDD}-{4자리 랜덤} — agent_tools.create_order 패턴과 통일.
        # 동시 합의 자동 주문에서 같은 초에 두 요청이 들어와도 충돌 가능성을 1/10000 로 낮춘다.
        # 23505 발생 시 호출처에서 재시도하므로 실질적으로 0 으로 수렴.
        date_str = datetime.now().strftime("%Y%m%d")
        rand_suffix = str(random.randint(1000, 9999))
        return f"ORD-{date_str}-{rand_suffix}"

    # ===========================================
    # 주문 ↔ 캘린더 동기화 헬퍼
    # ===========================================

    @staticmethod
    def _date_only(value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, str):
            return value[:10]
        if hasattr(value, "isoformat"):
            return value.isoformat()[:10]
        return str(value)[:10]

    @staticmethod
    def _calendar_user_ids_for_order(order: dict) -> list[str]:
        user_ids: list[str] = []
        for key in ("buyer_id", "seller_id"):
            value = order.get(key)
            if value is None:
                continue
            user_id = str(value)
            if user_id not in user_ids:
                user_ids.append(user_id)
        return user_ids

    def _build_order_calendar_payload(self, order: dict) -> dict[str, Any]:
        status_value = str(order.get("status") or "")
        status_label = ORDER_STATUS_LABELS.get(status_value, status_value)
        order_number = order.get("order_number") or str(order.get("id", ""))[:8]
        event_date = (
            self._date_only(order.get("delivery_date"))
            or self._date_only(order.get("created_at"))
            or datetime.now(timezone.utc).date().isoformat()
        )

        description_parts = [f"상태: {status_label}"]
        total_amount = order.get("total_amount")
        if total_amount is not None:
            description_parts.append(f"금액: {int(total_amount):,}원")
        if order.get("delivery_date"):
            description_parts.append(f"납기일: {self._date_only(order.get('delivery_date'))}")
        if order.get("delivery_address"):
            description_parts.append(f"배송지: {order['delivery_address']}")
        if order.get("notes"):
            description_parts.append(f"메모: {order['notes']}")

        return {
            "title": f"주문 {order_number} - {status_label}",
            "event_type": "ORDER",
            "event_date": event_date,
            "start_time": None,
            "end_time": None,
            "description": "\n".join(description_parts),
            "is_allday": True,
            "deleted_at": None,
        }

    def _soft_delete_calendar_events_for_order_sync(self, order_id: UUID | str) -> None:
        deleted_at = datetime.now(timezone.utc).isoformat()
        self.calendar_events.update({"deleted_at": deleted_at}).eq(
            "order_id", str(order_id)
        ).is_("deleted_at", None).execute()

    async def _soft_delete_calendar_events_for_order(self, order_id: UUID | str) -> None:
        await asyncio.to_thread(
            lambda: self._soft_delete_calendar_events_for_order_sync(order_id)
        )

    def _sync_calendar_events_for_order_sync(self, order: dict) -> None:
        """주문 상태/데이터를 양 당사자의 order-linked calendar_events에 반영한다.

        견고화 (2026-04-27 — 중복 누적 버그 수정):
        - CANCELLED 또는 soft-deleted 주문: 활성 calendar_events 전부 soft-delete
        - 그 외 상태: buyer/seller 각각 정확히 1개의 active row (target_event_date 기준)
          만 남기고, 같은 user 의 다른 active row 는 모두 soft-delete
            * 같은 event_date 의 중복 row 정리 (race condition 잔재)
            * 다른 event_date 의 잔존 row 정리 (납기일 변경 후 미정리)
        - INSERT 시 partial unique index 충돌(23505) 발생 가능 — 정상 race 이므로 무시
          (다른 동시 호출이 이미 INSERT 했음을 의미)

        보장: 한 주문(order_id) × 한 user(user_id) 당 active calendar_events 정확히 1개.
        """
        order_id = order.get("id")
        if not order_id:
            return
        order_id_str = str(order_id)

        if order.get("status") == ORDER_STATUS_CANCELLED or order.get("deleted_at"):
            self._soft_delete_calendar_events_for_order_sync(order_id_str)
            return

        user_ids = self._calendar_user_ids_for_order(order)
        if not user_ids:
            return

        payload_base = self._build_order_calendar_payload(order)
        target_event_date = payload_base["event_date"]
        deleted_at = datetime.now(timezone.utc).isoformat()

        # 한 번의 쿼리로 이 주문의 모든 active calendar_events 조회
        existing_result = (
            self.calendar_events.select("id,user_id,event_date,deleted_at,updated_at,created_at")
            .eq("order_id", order_id_str)
            .is_("deleted_at", None)
            .execute()
        )
        existing_rows = existing_result.data or []

        # user_id 별로 그룹핑
        rows_by_user: dict[str, list[dict]] = {}
        for row in existing_rows:
            uid = str(row.get("user_id"))
            rows_by_user.setdefault(uid, []).append(row)

        for user_id in user_ids:
            user_rows = rows_by_user.get(user_id, [])

            # 1) target_event_date 와 정확히 일치하는 active row 찾기
            #    (event_date 가 date 객체 또는 ISO 문자열로 올 수 있음 — 앞 10자리 비교)
            matching_rows: list[dict] = []
            other_rows: list[dict] = []
            for row in user_rows:
                row_date = row.get("event_date")
                row_date_str = str(row_date)[:10] if row_date is not None else None
                if row_date_str == target_event_date:
                    matching_rows.append(row)
                else:
                    other_rows.append(row)

            # 2) 보존할 row 결정 — matching 중 가장 최신 (updated_at DESC, created_at DESC)
            primary_id: Optional[str] = None
            if matching_rows:
                matching_rows.sort(
                    key=lambda r: (r.get("updated_at") or "", r.get("created_at") or ""),
                    reverse=True,
                )
                primary = matching_rows[0]
                primary_id = str(primary["id"])
                # 보존할 row 는 payload_base 로 UPDATE
                self.calendar_events.update(payload_base).eq("id", primary_id).execute()
                # matching 중 primary 를 제외한 나머지(중복) soft-delete
                for dup in matching_rows[1:]:
                    self.calendar_events.update({"deleted_at": deleted_at}).eq(
                        "id", str(dup["id"])
                    ).execute()

            # 3) 다른 event_date 를 가진 잔존 row 도 모두 soft-delete
            #    (납기일 변경 또는 과거 sync 누락으로 잔존)
            for stale in other_rows:
                self.calendar_events.update({"deleted_at": deleted_at}).eq(
                    "id", str(stale["id"])
                ).execute()

            # 4) matching row 가 없었으면 새로 INSERT
            if primary_id is None:
                try:
                    self.calendar_events.insert(
                        {
                            **payload_base,
                            "user_id": user_id,
                            "order_id": order_id_str,
                        }
                    ).execute()
                except PostgrestAPIError as e:
                    err_code = getattr(e, "code", "") or ""
                    err_msg = (getattr(e, "message", "") or "") + " " + str(e)
                    # partial unique index 충돌(23505) — 다른 동시 호출이 먼저 INSERT 했음.
                    # 정상 race 이므로 무시 (다음 sync 시점에 정합성 자연 회복).
                    if err_code == "23505" or "23505" in err_msg or "duplicate" in err_msg.lower():
                        print(
                            f"[order_service._sync_calendar_events_for_order_sync] "
                            f"unique conflict (race) — order_id={order_id_str}, "
                            f"user_id={user_id}, event_date={target_event_date} (무시)"
                        )
                        continue
                    raise

    async def _sync_calendar_events_for_order(self, order: dict) -> None:
        await asyncio.to_thread(
            lambda: self._sync_calendar_events_for_order_sync(order)
        )

    def sync_calendar_events_for_order_id(self, order_id: UUID | str) -> None:
        result = (
            self.orders.select("*")
            .eq("id", str(order_id))
            .is_("deleted_at", None)
            .execute()
        )
        if result.data:
            self._sync_calendar_events_for_order_sync(result.data[0])
            return
        self._soft_delete_calendar_events_for_order_sync(order_id)

    async def async_sync_calendar_events_for_order_id(self, order_id: UUID | str) -> None:
        await asyncio.to_thread(
            lambda: self.sync_calendar_events_for_order_id(order_id)
        )

    # ===========================================
    # 주문 ↔ 채팅 통합 헬퍼
    # ===========================================
    async def _ensure_chat_room_for_order(self, order: dict) -> Optional[dict]:
        """주문에 연결된 채팅방을 조회하거나 생성한다.

        주문별 채팅방 정책:
        - 같은 buyer/seller라도 order_id가 다르면 다른 채팅방을 만든다.
        - 기존 일반 채팅방(order_id 없음)이나 다른 주문 채팅방의 order_id를 덮어쓰지 않는다.
        """
        try:
            seller_id = str(order["seller_id"])
            buyer_id = str(order["buyer_id"])
            order_id = str(order["id"])

            # 1) 이 주문에 이미 연결된 채팅방만 검색
            existing = await asyncio.to_thread(
                lambda: chat_service.rooms.select("*")
                .eq("seller_id", seller_id)
                .eq("buyer_id", buyer_id)
                .eq("order_id", order_id)
                .limit(1)
                .execute()
            )

            if existing.data:
                return existing.data[0]

            # 2) 없으면 이 주문 전용 새 채팅방 생성
            create_result = await asyncio.to_thread(
                lambda: chat_service.rooms.insert(
                    {
                        "seller_id": seller_id,
                        "buyer_id": buyer_id,
                        "order_id": order_id,
                    }
                ).execute()
            )

            if not create_result.data:
                return None

            return create_result.data[0]

        except Exception as e:
            print(f"[order_service] _ensure_chat_room_for_order 실패: {type(e).__name__}: {e}")
            return None

    async def _sync_offer_status_in_messages(
        self, offer_id: UUID | str, new_status: str
    ) -> None:
        """messages 테이블의 metadata.offer_id 가 일치하는 행들의 metadata.status 동기화.

        협상가(offer) 가 ACCEPTED/REJECTED/SUPERSEDED 로 전환될 때 호출.
        프론트(MessageBubble) 가 metadata.status === 'PENDING' 일 때만 수락/거절 버튼을
        보여주므로, 동기화하지 않으면 stale 한 버튼이 계속 노출된다.

        구현 정책:
          1) RPC 함수(sync_offer_status_in_messages) 우선 시도 — 단일 SQL UPDATE 로 빠름
          2) 실패 시 fetch → mutate → update fallback (PostgREST `metadata->>offer_id` 사용)

        실패해도 주문/협상 처리 자체는 막지 않는다 (예외 무시 + 로그).
        """
        offer_id_str = str(offer_id)
        try:
            # 1) RPC 함수로 한 번에 UPDATE 시도 (마이그레이션 20260427000005)
            await asyncio.to_thread(
                lambda: self.client.rpc(
                    "sync_offer_status_in_messages",
                    {"p_offer_id": offer_id_str, "p_new_status": new_status},
                ).execute()
            )
            return
        except Exception as rpc_err:
            print(
                f"[order_service._sync_offer_status_in_messages] RPC 실패, fallback 시도: "
                f"{type(rpc_err).__name__}: {rpc_err}"
            )

        # 2) Fallback: fetch → mutate → update (PostgREST 의 metadata->>offer_id 필터 사용)
        try:
            rows = await asyncio.to_thread(
                lambda: self.client.table("messages")
                .select("id, metadata")
                .eq("metadata->>offer_id", offer_id_str)
                .execute()
            )
            for row in rows.data or []:
                meta = dict(row.get("metadata") or {})
                meta["status"] = new_status
                row_id = row["id"]
                await asyncio.to_thread(
                    lambda rid=row_id, m=meta: self.client.table("messages")
                    .update({"metadata": m})
                    .eq("id", rid)
                    .execute()
                )
        except Exception as e:
            print(
                f"[order_service._sync_offer_status_in_messages] fallback UPDATE 실패 "
                f"(무시): offer_id={offer_id_str}, new_status={new_status}, "
                f"error={type(e).__name__}: {e}"
            )

    async def _emit_chat_event(
        self,
        room: dict,
        sender_id: str,
        message_type: str,
        content: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """채팅방에 이벤트 메시지를 INSERT 하고 WebSocket broadcast 한다.

        실패 시에도 주문 처리 자체는 막지 않는다 (예외 무시 + 로그만).
        """
        try:
            message = await chat_service.send_event_message(
                room_id=room["id"],
                sender_id=sender_id,
                message_type=message_type,
                content=content,
                metadata=metadata,
                is_read=False,
            )
            if not message:
                return

            # WebSocket broadcast (chat_ws.py 메시지 형식과 동일)
            broadcast_payload: dict[str, Any] = {
                "type": "message",
                "id": str(message.get("id", "")),
                "room_id": str(message.get("room_id", "")),
                "sender_id": str(message.get("sender_id", "")),
                "content": message.get("content", ""),
                "is_read": message.get("is_read", False),
                "created_at": message.get("created_at"),
                "message_type": message.get("message_type", message_type),
                "metadata": message.get("metadata"),
            }
            try:
                await ws_manager.broadcast(str(room["id"]), broadcast_payload)
            except Exception as e:
                print(f"[order_service] WS broadcast 실패: {type(e).__name__}: {e}")
        except Exception as e:
            print(f"[order_service] _emit_chat_event 실패: {type(e).__name__}: {e}")

    # ===========================================
    # 알림(Notification) emit 헬퍼
    # ===========================================
    async def _get_user_meta(self, user_id: str) -> dict:
        """notification 발신자 표시용 사용자 정보 조회 (name, company_name, role).

        조회 실패 시 빈 dict — emit 흐름은 끊지 않고 계속.
        """
        try:
            result = await asyncio.to_thread(
                lambda: self.client.table("users")
                .select("id, name, company_name, role")
                .eq("id", user_id)
                .single()
                .execute()
            )
            return result.data or {}
        except Exception as e:
            print(
                f"[order_service._get_user_meta] 조회 실패 (무시): "
                f"user_id={user_id}, error={type(e).__name__}: {e}"
            )
            return {}

    @staticmethod
    def _build_order_link(order_id: str, recipient_role: str) -> str:
        """알림 link_url — 수신자 역할 기준 (buyer/seller) 으로 라우팅."""
        prefix = "buyer" if recipient_role == "BUYER" else "seller"
        return f"/{prefix}/orders?id={order_id}"

    async def _emit_order_notification(
        self,
        *,
        order: dict,
        sender_id: str,
        notif_type: str,
        title: str,
        body: str,
    ) -> None:
        """주문 관련 알림을 상대방(수신자) 한 명에게 emit.

        - order 의 buyer_id/seller_id 중 sender_id 가 아닌 쪽이 수신자.
        - 자기 자신에게는 보내지 않음 (sender_id == receiver_id 면 skip).
        - 실패해도 다른 흐름 막지 않음 (try/except + 로그).
        """
        try:
            buyer_id = str(order.get("buyer_id") or "")
            seller_id = str(order.get("seller_id") or "")
            order_id = str(order.get("id") or "")
            sender_id_str = str(sender_id)

            if not order_id or not buyer_id or not seller_id:
                return

            # 수신자 결정
            if sender_id_str == buyer_id:
                receiver_id = seller_id
                receiver_role = "SELLER"
            elif sender_id_str == seller_id:
                receiver_id = buyer_id
                receiver_role = "BUYER"
            else:
                # sender 가 주문 당사자가 아님 → 어디로 보낼지 모름, skip
                return

            # 자기 자신 skip
            if receiver_id == sender_id_str:
                return

            await notification_service.emit(
                user_id=receiver_id,
                notification_type=notif_type,
                title=title,
                body=body,
                link_url=self._build_order_link(order_id, receiver_role),
                order_id=order_id,
            )
        except Exception as e:
            print(
                f"[order_service._emit_order_notification] 실패 (무시): "
                f"type={notif_type}, error={type(e).__name__}: {e}"
            )

    async def list_orders(
        self,
        *,
        user_id: UUID,
        role: str,
        status: Optional[str] = None,
        status_in: Optional[list[str]] = None,
        partner_user_id: Optional[UUID] = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[dict], PaginationMeta]:
        # join 임베딩으로 한 번에 buyer/seller/products 정보까지 가져온다 (N+1 제거)
        query = self.orders.select(ORDER_SELECT_WITH_JOINS, count="exact").is_("deleted_at", None)

        # 역할에 따라 필터 (단, partner_user_id 가 있으면 양방향 OR 가 우선)
        # 양방향 패턴은 partner_service.get_stats / _attach_last_trades 와 동일 — me ↔ counterpart.
        if partner_user_id is not None:
            user_id_str = str(user_id)
            counterpart_str = str(partner_user_id)
            query = query.or_(
                f"and(buyer_id.eq.{user_id_str},seller_id.eq.{counterpart_str}),"
                f"and(seller_id.eq.{user_id_str},buyer_id.eq.{counterpart_str})"
            )
        elif role == "BUYER":
            query = query.eq("buyer_id", str(user_id))
        else:
            query = query.eq("seller_id", str(user_id))

        # status_in 우선, 없으면 단일 status (backward compat)
        # 빈 list 인 경우 결과 없음 — .in_("status", []) 는 PostgREST 가 정상 처리하나
        # 의도 명확화 + 일부 supabase-py 버전 호환을 위해 빈 list 도 단일 status fallback 안 함
        if status_in:
            query = query.in_("status", status_in)
        elif status:
            query = query.eq("status", status)

        offset = (page - 1) * limit
        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)

        result = await asyncio.to_thread(lambda: query.execute())
        total = result.count or 0

        orders = [_flatten_order_row(row) for row in (result.data or [])]

        meta = PaginationMeta(
            total=total,
            page=page,
            limit=limit,
            total_pages=math.ceil(total / limit) if total > 0 else 0,
        )
        return orders, meta

    async def get_order(self, order_id: UUID) -> Optional[dict]:
        # join 임베딩으로 buyer/seller/products 정보 포함
        result = await asyncio.to_thread(
            lambda: self.orders.select(ORDER_SELECT_WITH_JOINS)
            .eq("id", str(order_id))
            .is_("deleted_at", None)
            .execute()
        )
        if not result.data:
            return None
        return _flatten_order_row(result.data[0])

    async def _get_order_or_404(self, order_id: UUID) -> dict:
        order = await self.get_order(order_id)
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Order not found"
            )
        return order

    @staticmethod
    def _assert_participant(order: dict, user_id: str) -> str:
        """사용자가 주문 당사자인지 확인하고 역할(SELLER/BUYER) 반환"""
        if order["buyer_id"] == user_id:
            return "BUYER"
        if order["seller_id"] == user_id:
            return "SELLER"
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    async def create_order(
        self,
        buyer_id: UUID,
        data: dict,
        auto_confirm: bool = False,
    ) -> dict:
        """주문 생성.

        auto_confirm 분기 (AI 도구 흐름 전용):
          - False (기본 / CreateOrderModal 경로): 기존 동작 그대로 — status='QUOTE_REQUESTED'
            로 INSERT 후 채팅방에 "새 견적 요청" SYSTEM 메시지 발송. 판매자 검토 대기.
          - True (구매자가 상품 목록 가격 그대로 구매하려는 의도):
              * 모든 라인의 unit_price 가 products.price_per_unit 와 같거나 높으면 →
                즉시 CONFIRMED 로 INSERT + 판매자 재고 자동 차감 + 채팅방에 "주문 확정" SYSTEM
                메시지 발송 (납품일 포함). 재고 부족 시 HTTPException 으로 실패.
              * 한 라인이라도 unit_price < price_per_unit (구매자가 가격을 깎음) 이면 →
                일반 QUOTE_REQUESTED 로 INSERT 후 즉시 자동 counter offer 생성
                (submit_counter_offer 가 NEGOTIATING 자동 전환 + 채팅방에 PENDING 카드 노출).
        """
        items_data = data.pop("items", [])

        # 총액 계산
        total = sum(item["quantity"] * item["unit_price"] for item in items_data)

        # ────────────────────────────────────────────
        # auto_confirm 사전 분기 — 상품 단가와 비교해 초기 status 결정
        # ────────────────────────────────────────────
        # 비교 결과:
        #   "MATCH"     — 모든 라인 unit_price >= price_per_unit → CONFIRMED 로 INSERT
        #   "NEGOTIATE" — 한 라인이라도 unit_price < price_per_unit → QUOTE_REQUESTED + 자동 카운터오퍼
        #   None        — auto_confirm=False (기본 흐름)
        auto_confirm_decision: Optional[str] = None
        product_meta_by_id: dict[str, dict] = {}  # product_id -> {"name", "unit", "price_per_unit"}
        if auto_confirm and items_data:
            try:
                product_ids = list({str(i["product_id"]) for i in items_data})
                products_result = await asyncio.to_thread(
                    lambda: self.client.table("products")
                    .select("id, name, unit, price_per_unit")
                    .in_("id", product_ids)
                    .is_("deleted_at", None)
                    .execute()
                )
                for p in products_result.data or []:
                    product_meta_by_id[str(p["id"])] = p

                negotiate = False
                for item in items_data:
                    pid = str(item["product_id"])
                    pmeta = product_meta_by_id.get(pid)
                    if not pmeta or pmeta.get("price_per_unit") is None:
                        # 상품을 못 찾으면 안전하게 기존 흐름(QUOTE_REQUESTED)으로 회귀
                        negotiate = True
                        auto_confirm_decision = None
                        break
                    listed = int(pmeta["price_per_unit"])
                    offered = int(item["unit_price"])
                    if offered < listed:
                        negotiate = True
                        # 협상 흐름은 break 해도 되지만, 메시지 표시용으로 product_meta 는 유지
                        break

                if auto_confirm_decision is None:
                    auto_confirm_decision = "NEGOTIATE" if negotiate else "MATCH"
            except Exception as e:
                print(
                    f"[order_service.create_order] auto_confirm 가격 비교 실패 (기본 흐름으로 회귀): "
                    f"{type(e).__name__}: {e}"
                )
                auto_confirm_decision = None

        # 초기 status 결정 — MATCH 만 CONFIRMED 직접 INSERT, 그 외는 QUOTE_REQUESTED
        initial_status = "CONFIRMED" if auto_confirm_decision == "MATCH" else "QUOTE_REQUESTED"

        base_payload = {
            **data,
            "buyer_id": str(buyer_id),
            "seller_id": str(data["seller_id"]),
            "total_amount": total,
            "status": initial_status,
        }

        # order_number UNIQUE 충돌 시 최대 3회 재생성 + 재시도 (동시 합의 자동 주문 보호)
        order = None
        last_error: Optional[Exception] = None
        for attempt in range(3):
            order_payload = {
                **base_payload,
                "order_number": self._generate_order_number(),
            }
            try:
                result = await asyncio.to_thread(
                    lambda p=order_payload: self.orders.insert(p).execute()
                )
                order = result.data[0]
                break
            except PostgrestAPIError as e:
                err_code = getattr(e, "code", "") or ""
                err_msg = (getattr(e, "message", "") or "") + " " + str(e)
                # 23505 (unique_violation) 만 재시도, 나머지는 즉시 raise
                if err_code == "23505" or "23505" in err_msg or "duplicate" in err_msg.lower():
                    last_error = e
                    continue
                raise
        if order is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="주문 번호 생성에 반복 실패했습니다. 잠시 후 다시 시도해주세요.",
            ) from last_error

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

        # ────────────────────────────────────────────
        # MATCH 분기: CONFIRMED 로 INSERT 했으니 판매자 재고 차감
        # ────────────────────────────────────────────
        # 재고 부족 시 update_status 와 동일한 의미로 HTTPException(400) 을 던진다.
        # 호출자(API/agent_tools)는 이 케이스에서 주문이 이미 INSERT 됐다는 점을 인지해야 한다 —
        # update_status(CONFIRMED) 가 실패한 것과 동치이므로 buyer 가 재시도 시 같은 주문을
        # CANCELLED 처리하거나 NEGOTIATING 으로 진행할 수 있도록 주문 행은 보존한다.
        if auto_confirm_decision == "MATCH":
            inventory_result = await self._deduct_seller_stock_for_order(order["id"])
            if not inventory_result.get("success"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=inventory_result.get("error", "재고 차감에 실패했습니다."),
                )

        created_order = await self.get_order(order["id"])
        if created_order:
            await self._sync_calendar_events_for_order(created_order)

        # ────────────────────────────────────────────
        # 채팅방 자동 연결 + 분기별 시스템 메시지
        # ────────────────────────────────────────────
        try:
            room = await self._ensure_chat_room_for_order(order)
            if room:
                if auto_confirm_decision == "MATCH":
                    # 즉시 확정 — 납품일 포함한 사용자 친화 SYSTEM 메시지
                    delivery_date_str = self._date_only(order.get("delivery_date"))
                    if delivery_date_str:
                        try:
                            d = datetime.fromisoformat(delivery_date_str).date()
                            delivery_label = f"{d.month}월 {d.day}일"
                        except Exception:
                            delivery_label = delivery_date_str
                    else:
                        delivery_label = "협의 예정"

                    # 첫 라인 기준 표시 (다중 라인 케이스는 외 N건)
                    first_item = items_data[0] if items_data else {}
                    pid = str(first_item.get("product_id", ""))
                    pmeta = product_meta_by_id.get(pid, {})
                    pname = pmeta.get("name") or "상품"
                    punit = pmeta.get("unit") or ""
                    qty = first_item.get("quantity", 0)
                    extra = ""
                    if len(items_data) > 1:
                        extra = f" 외 {len(items_data) - 1}건"
                    content = (
                        f"{pname} {qty}{punit}{extra} 주문이 확정되었습니다. "
                        f"납품일은 {delivery_label} 입니다."
                    )
                    await self._emit_chat_event(
                        room=room,
                        sender_id=str(order["buyer_id"]),
                        message_type="ORDER_STATUS",
                        content=content,
                        metadata={
                            "order_id": str(order["id"]),
                            "order_number": order["order_number"],
                            "from_status": "QUOTE_REQUESTED",
                            "to_status": "CONFIRMED",
                        },
                    )
                else:
                    # QUOTE_REQUESTED — 기존 견적 요청 시스템 메시지
                    await self._emit_chat_event(
                        room=room,
                        sender_id=str(order["seller_id"]),
                        message_type="SYSTEM",
                        content=(
                            f"새 견적 요청이 도착했습니다 - {order['order_number']}"
                        ),
                        metadata={
                            "order_id": str(order["id"]),
                            "order_number": order["order_number"],
                            "total_amount": order.get("total_amount"),
                        },
                    )
        except Exception as e:
            # 채팅 자동 연결 실패는 주문 생성을 막지 않음
            print(f"[order_service.create_order] chat 자동 연결 실패 (무시): {type(e).__name__}: {e}")

        # ────────────────────────────────────────────
        # NEGOTIATE 분기: 자동 카운터오퍼 발사 (PENDING 카드)
        # ────────────────────────────────────────────
        # submit_counter_offer 가 QUOTE_REQUESTED → NEGOTIATING 자동 전환 + 채팅 PENDING
        # 카드 발송까지 처리한다. buyer 가 제시한 합계 금액으로 그대로 박는다.
        if auto_confirm_decision == "NEGOTIATE":
            try:
                proposed_items = [
                    {
                        "product_id": str(i["product_id"]),
                        "quantity": int(i["quantity"]),
                        "unit_price": int(i["unit_price"]),
                        "notes": i.get("notes"),
                    }
                    for i in items_data
                ]
                buyer_user = {"id": str(buyer_id), "role": "BUYER"}
                await self.submit_counter_offer(
                    order_id=order["id"],
                    payload={
                        "proposed_total_amount": int(total),
                        "proposed_items": proposed_items,
                        "notes": data.get("notes") or "구매자 제시 가격 (자동 협상)",
                    },
                    user=buyer_user,
                )
                # submit_counter_offer 안에서 status 가 NEGOTIATING 으로 전환되므로
                # 응답에 반영하기 위해 created_order 를 다시 로드한다.
                created_order = await self.get_order(order["id"])
            except Exception as e:
                # 카운터오퍼 자동 발사 실패는 주문 자체를 막지 않음 (QUOTE_REQUESTED 상태로 남김)
                print(
                    f"[order_service.create_order] 자동 카운터오퍼 실패 (QUOTE_REQUESTED 유지): "
                    f"{type(e).__name__}: {e}"
                )

        if not created_order:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Created order could not be loaded",
            )
        return created_order
    
    async def _deduct_seller_stock_for_order(self, order_id: UUID | str) -> dict:
        """
        주문이 CONFIRMED 상태로 확정될 때 판매자 재고를 차감한다.
        orders.inventory_deducted_at 값으로 중복 차감을 방지한다.
        """
        order_id_str = str(order_id)

        try:
            # 1. 주문 조회: 이미 재고 차감된 주문인지 확인
            order_result = await asyncio.to_thread(
                lambda: self.orders.select("id, inventory_deducted_at")
                .eq("id", order_id_str)
                .is_("deleted_at", None)
                .limit(1)
                .execute()
            )

            if not order_result.data:
                return {
                    "success": False,
                    "error": "재고 차감 대상 주문을 찾을 수 없습니다.",
                }

            order = order_result.data[0]

            # 이미 차감된 주문이면 다시 차감하지 않음
            if order.get("inventory_deducted_at"):
                return {
                    "success": True,
                    "message": "이미 재고가 차감된 주문입니다.",
                    "already_deducted": True,
                }

            # 2. 주문 항목 조회
            items_result = await asyncio.to_thread(
                lambda: self.items.select("id, product_id, quantity")
                .eq("order_id", order_id_str)
                .execute()
            )

            order_items = items_result.data or []

            if not order_items:
                return {
                    "success": False,
                    "error": "주문 항목이 없어 재고를 차감할 수 없습니다.",
                }

            # 3. 먼저 전체 재고 충분 여부 검사
            stock_checks = []

            for item in order_items:
                product_id = item.get("product_id")
                quantity = item.get("quantity")

                if not product_id or quantity is None:
                    return {
                        "success": False,
                        "error": "주문 항목에 product_id 또는 quantity가 없습니다.",
                    }

                product_result = await asyncio.to_thread(
                    lambda pid=product_id: self.client.table("products")
                    .select("id, name, stock_quantity, status")
                    .eq("id", str(pid))
                    .is_("deleted_at", None)
                    .limit(1)
                    .execute()
                )

                if not product_result.data:
                    return {
                        "success": False,
                        "error": f"상품을 찾을 수 없습니다. product_id={product_id}",
                    }

                product = product_result.data[0]
                current_stock = int(product.get("stock_quantity") or 0)
                order_quantity = int(quantity)

                if current_stock < order_quantity:
                    return {
                        "success": False,
                        "error": (
                            f"'{product.get('name')}' 재고가 부족합니다. "
                            f"현재 재고: {current_stock}, 확정 수량: {order_quantity}"
                        ),
                    }

                stock_checks.append({
                    "product_id": str(product_id),
                    "product_name": product.get("name"),
                    "current_stock": current_stock,
                    "order_quantity": order_quantity,
                    "new_stock": current_stock - order_quantity,
                })

            # 4. 재고 차감 실행
            deducted_items = []

            for stock in stock_checks:
                new_stock = stock["new_stock"]

                if new_stock == 0:
                    new_status = "OUT_OF_STOCK"
                elif new_stock < 10:
                    new_status = "LOW_STOCK"
                else:
                    new_status = "NORMAL"

                await asyncio.to_thread(
                    lambda s=stock, ns=new_stock, st=new_status: self.client.table("products")
                    .update({
                        "stock_quantity": ns,
                        "status": st,
                    })
                    .eq("id", s["product_id"])
                    .execute()
                )

                deducted_items.append({
                    "product_id": stock["product_id"],
                    "product_name": stock["product_name"],
                    "before_quantity": stock["current_stock"],
                    "deducted_quantity": stock["order_quantity"],
                    "after_quantity": new_stock,
                    "new_status": new_status,
                })

            # 5. 주문에 재고 차감 완료 시각 기록
            now_utc = datetime.now(timezone.utc).isoformat()

            await asyncio.to_thread(
                lambda: self.orders.update({
                    "inventory_deducted_at": now_utc,
                })
                .eq("id", order_id_str)
                .execute()
            )

            return {
                "success": True,
                "message": "판매자 재고가 차감되었습니다.",
                "deducted_items": deducted_items,
                "inventory_deducted_at": now_utc,
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"재고 차감 중 오류가 발생했습니다: {str(e)}",
            }

    async def _add_buyer_inventory_for_order(self, order_id: UUID | str) -> None:
        """주문이 COMPLETED 로 진입할 때 buyer 재고를 누적한다.

        설계 (옵션 A — buyer_inventories 테이블 신설):
          - 멱등성: orders.inventory_added_at 이 이미 채워져 있으면 skip.
          - order_items 를 product_id 별 quantity 합산 (같은 상품 여러 라인 케이스).
          - 각 (buyer_id, product_id) active row UPSERT:
              * 있으면 quantity += 합산값, last_added_at = NOW(), unit 업데이트
              * 없으면 INSERT (quantity = 합산값)
          - orders.inventory_added_at = NOW() 기록.

        실패 정책:
          본 함수는 절대 raise 하지 않는다 (logger.error 만). 호출처(update_status 의
          COMPLETED 분기) 가 best-effort 로 호출하므로, 누적 실패가 COMPLETED 전이를
          막지 않는다 — 사용자 입장에선 주문 완료가 더 중요하고, 재고는 추후 수동 보정 가능.
        """
        order_id_str = str(order_id)

        try:
            # 1) 주문 + 멱등성 체크 — inventory_added_at 이미 있으면 skip
            order_result = await asyncio.to_thread(
                lambda: self.orders.select("id, buyer_id, inventory_added_at")
                .eq("id", order_id_str)
                .is_("deleted_at", None)
                .limit(1)
                .execute()
            )
            order_rows = order_result.data or []
            if not order_rows:
                logger.error(
                    "[order_service._add_buyer_inventory_for_order] order not found "
                    "order_id=%s",
                    order_id_str,
                )
                return

            order = order_rows[0]
            if order.get("inventory_added_at"):
                # 이미 누적됨 — 멱등 skip
                return

            buyer_id = order.get("buyer_id")
            if not buyer_id:
                logger.error(
                    "[order_service._add_buyer_inventory_for_order] buyer_id 없음 "
                    "order_id=%s",
                    order_id_str,
                )
                return
            buyer_id_str = str(buyer_id)

            # 2) order_items 조회 + product_id 별 quantity 합산
            items_result = await asyncio.to_thread(
                lambda: self.items.select("product_id, quantity")
                .eq("order_id", order_id_str)
                .execute()
            )
            items_data = items_result.data or []
            if not items_data:
                # 아이템 없는 주문 — 누적 대상 없음. 멱등성만 기록하고 종료.
                now_utc = datetime.now(timezone.utc).isoformat()
                await asyncio.to_thread(
                    lambda: self.orders.update({"inventory_added_at": now_utc})
                    .eq("id", order_id_str)
                    .execute()
                )
                return

            # product_id 별 합산
            qty_by_product: dict[str, int] = {}
            for item in items_data:
                pid = item.get("product_id")
                qty = item.get("quantity")
                if not pid or qty is None:
                    continue
                pid_str = str(pid)
                qty_by_product[pid_str] = qty_by_product.get(pid_str, 0) + int(qty)

            if not qty_by_product:
                now_utc = datetime.now(timezone.utc).isoformat()
                await asyncio.to_thread(
                    lambda: self.orders.update({"inventory_added_at": now_utc})
                    .eq("id", order_id_str)
                    .execute()
                )
                return

            # 3) 합산 결과로 buyer_inventories UPSERT
            buyer_inventories_table = self.client.table("buyer_inventories")
            now_utc_iso = datetime.now(timezone.utc).isoformat()

            # 상품 unit 조회용 (한 번에 batch 조회)
            product_ids = list(qty_by_product.keys())
            products_lookup: dict[str, dict] = {}
            if product_ids:
                products_result = await asyncio.to_thread(
                    lambda: self.client.table("products")
                    .select("id, unit")
                    .in_("id", product_ids)
                    .execute()
                )
                for p in products_result.data or []:
                    products_lookup[str(p["id"])] = p

            for pid_str, add_qty in qty_by_product.items():
                product_unit = products_lookup.get(pid_str, {}).get("unit")

                # 기존 active row 조회
                existing_result = await asyncio.to_thread(
                    lambda p=pid_str: buyer_inventories_table.select(
                        "id, quantity"
                    )
                    .eq("buyer_id", buyer_id_str)
                    .eq("product_id", p)
                    .is_("deleted_at", None)
                    .limit(1)
                    .execute()
                )
                existing_rows = existing_result.data or []

                if existing_rows:
                    # UPDATE — 기존 quantity 에 add_qty 합산
                    existing = existing_rows[0]
                    new_qty = int(existing.get("quantity") or 0) + add_qty
                    update_payload = {
                        "quantity": new_qty,
                        "last_added_at": now_utc_iso,
                    }
                    if product_unit:
                        update_payload["unit"] = product_unit
                    try:
                        await asyncio.to_thread(
                            lambda eid=str(existing["id"]),
                            up=update_payload: buyer_inventories_table.update(up)
                            .eq("id", eid)
                            .is_("deleted_at", None)
                            .execute()
                        )
                    except Exception as upd_err:
                        logger.error(
                            "[order_service._add_buyer_inventory_for_order] update 실패 "
                            "order_id=%s buyer_id=%s product_id=%s err=%s: %s",
                            order_id_str,
                            buyer_id_str,
                            pid_str,
                            type(upd_err).__name__,
                            upd_err,
                        )
                        # 한 상품 실패해도 다른 상품은 계속 처리
                        continue
                else:
                    # INSERT — 새 row
                    insert_payload = {
                        "buyer_id": buyer_id_str,
                        "product_id": pid_str,
                        "quantity": add_qty,
                        "unit": product_unit,
                        "last_added_at": now_utc_iso,
                    }
                    try:
                        await asyncio.to_thread(
                            lambda p=insert_payload: buyer_inventories_table.insert(p).execute()
                        )
                    except PostgrestAPIError as ins_err:
                        # 23505 — partial unique index 충돌 (race: 다른 동시 호출이 INSERT 후)
                        # → fallback: 다시 SELECT 한 뒤 UPDATE
                        err_code = getattr(ins_err, "code", "") or ""
                        err_msg = str(ins_err)
                        if (
                            err_code == "23505"
                            or "23505" in err_msg
                            or "duplicate" in err_msg.lower()
                        ):
                            try:
                                race_result = await asyncio.to_thread(
                                    lambda p=pid_str: buyer_inventories_table.select(
                                        "id, quantity"
                                    )
                                    .eq("buyer_id", buyer_id_str)
                                    .eq("product_id", p)
                                    .is_("deleted_at", None)
                                    .limit(1)
                                    .execute()
                                )
                                race_rows = race_result.data or []
                                if race_rows:
                                    race_row = race_rows[0]
                                    race_qty = (
                                        int(race_row.get("quantity") or 0) + add_qty
                                    )
                                    upd_payload = {
                                        "quantity": race_qty,
                                        "last_added_at": now_utc_iso,
                                    }
                                    if product_unit:
                                        upd_payload["unit"] = product_unit
                                    await asyncio.to_thread(
                                        lambda rid=str(race_row["id"]),
                                        up=upd_payload: buyer_inventories_table.update(
                                            up
                                        )
                                        .eq("id", rid)
                                        .is_("deleted_at", None)
                                        .execute()
                                    )
                            except Exception as race_err:
                                logger.error(
                                    "[order_service._add_buyer_inventory_for_order] "
                                    "race fallback 실패 order_id=%s product_id=%s "
                                    "err=%s: %s",
                                    order_id_str,
                                    pid_str,
                                    type(race_err).__name__,
                                    race_err,
                                )
                                continue
                        else:
                            logger.error(
                                "[order_service._add_buyer_inventory_for_order] "
                                "insert 실패 order_id=%s buyer_id=%s product_id=%s "
                                "err=%s: %s",
                                order_id_str,
                                buyer_id_str,
                                pid_str,
                                type(ins_err).__name__,
                                ins_err,
                            )
                            continue
                    except Exception as ins_err2:
                        logger.error(
                            "[order_service._add_buyer_inventory_for_order] "
                            "insert 일반 실패 order_id=%s product_id=%s err=%s: %s",
                            order_id_str,
                            pid_str,
                            type(ins_err2).__name__,
                            ins_err2,
                        )
                        continue

            # 4) 멱등성 — orders.inventory_added_at 기록
            now_utc = datetime.now(timezone.utc).isoformat()
            try:
                await asyncio.to_thread(
                    lambda: self.orders.update({"inventory_added_at": now_utc})
                    .eq("id", order_id_str)
                    .execute()
                )
            except Exception as flag_err:
                logger.error(
                    "[order_service._add_buyer_inventory_for_order] "
                    "inventory_added_at 기록 실패 order_id=%s err=%s: %s",
                    order_id_str,
                    type(flag_err).__name__,
                    flag_err,
                )

        except Exception as e:
            # 최상위 try — buyer 재고 누적은 절대 호출처(COMPLETED 전이)를 막지 않는다.
            logger.error(
                "[order_service._add_buyer_inventory_for_order] 누적 전체 실패 (무시) "
                "order_id=%s err=%s: %s",
                order_id_str,
                type(e).__name__,
                e,
            )

    async def update_status(
        self, order_id: UUID, user_id: UUID, new_status: str
    ) -> Optional[dict]:
        # 주문 당사자(seller 또는 buyer) 확인 후 업데이트
        # soft-deleted 주문은 상태 변경 차단
        order = await self._get_order_or_404(order_id)
        user_id_str = str(user_id)
        actor_role = self._assert_participant(order, user_id_str)
        current_status = order["status"]

        # 상태 전이 가드 (전이 자체가 허용되는지)
        allowed = ALLOWED_TRANSITIONS.get(current_status, set())
        if new_status not in allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status transition: {current_status} → {new_status}",
            )

        # 역할 가드 (페어별 화이트리스트)
        # 매트릭스에 등록되지 않은 페어는 어느 역할도 진행 불가 (방어적)
        allowed_roles = TRANSITION_ROLE_GUARD.get((current_status, new_status), set())
        if actor_role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="권한이 없습니다",
            )
        
        # CONFIRMED로 확정되는 순간 판매자 재고 차감
        inventory_deduction_result = None

        if new_status == "CONFIRMED":
            inventory_deduction_result = await self._deduct_seller_stock_for_order(order_id)

            if not inventory_deduction_result.get("success"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=inventory_deduction_result.get("error", "재고 차감에 실패했습니다."),
                )

        await asyncio.to_thread(
            lambda: self.orders.update({"status": new_status})
            .eq("id", str(order_id))
            .is_("deleted_at", None)
            .execute()
        )
        updated_order = await self.get_order(order_id)
        if updated_order:
            await self._sync_calendar_events_for_order(updated_order)

        # COMPLETED 진입 시 buyer 재고 자동 누적 (옵션 A — buyer_inventories)
        # _deduct_seller_stock_for_order 와 달리 실패해도 raise 하지 않음 — 사용자 입장에선
        # 주문 완료가 더 중요. 누적 실패는 logger.error 로만 남기고 흐름 계속.
        if new_status == "COMPLETED":
            try:
                await self._add_buyer_inventory_for_order(order_id)
            except Exception as e:
                logger.error(
                    "[order_service.update_status] buyer 재고 누적 실패 (무시) "
                    "order_id=%s err=%s: %s",
                    str(order_id),
                    type(e).__name__,
                    e,
                )

        # 주요 상태 전환만 채팅에 반영 (너무 시끄럽지 않게)
        # CONFIRMED, PREPARING, SHIPPING, COMPLETED 만 알림 — 그 외는 skip
        # NEGOTIATING 으로의 전환은 협상가 메시지로 이미 표현됨
        notify_statuses = {"CONFIRMED", "PREPARING", "SHIPPING", "COMPLETED"}
        if new_status in notify_statuses:
            label = {
                "CONFIRMED": "확정",
                "PREPARING": "준비 중",
                "SHIPPING": "배송 중",
                "COMPLETED": "완료",
            }.get(new_status, new_status)
            try:
                room = await self._ensure_chat_room_for_order(order)
                if room:
                    await self._emit_chat_event(
                        room=room,
                        sender_id=user_id_str,
                        message_type="ORDER_STATUS",
                        content=f"주문 {label} - {order.get('order_number','')}",
                        metadata={
                            "order_id": str(order_id),
                            "order_number": order.get("order_number"),
                            "from_status": current_status,
                            "to_status": new_status,
                        },
                    )
            except Exception as e:
                print(
                    f"[order_service.update_status] chat event 실패 (무시): "
                    f"{type(e).__name__}: {e}"
                )

            # 알림 emit — 상대방에게 (상태 변경자가 아닌 쪽)
            order_number = order.get("order_number", "")
            await self._emit_order_notification(
                order=order,
                sender_id=user_id_str,
                notif_type="ORDER_STATUS",
                title="주문 상태 변경",
                body=f"주문 #{order_number} → {label}",
            )

        return updated_order

    async def update_order(
        self, order_id: UUID, payload: dict, user: dict
    ) -> dict:
        """견적 요청(QUOTE_REQUESTED) 단계에서 buyer 본인만 수정 가능"""
        order = await self._get_order_or_404(order_id)
        user_id_str = str(user["id"])

        if order["buyer_id"] != user_id_str:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the buyer can update this order",
            )
        if order["status"] != "QUOTE_REQUESTED":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Order can only be updated while in QUOTE_REQUESTED status",
            )

        items_payload = payload.pop("items", None)

        # None 값 필드는 update에서 제외 (미전달 = 변경 안 함)
        update_fields = {k: v for k, v in payload.items() if v is not None}

        # items 교체 시 총액 재계산
        if items_payload is not None:
            new_total = sum(i["quantity"] * i["unit_price"] for i in items_payload)
            update_fields["total_amount"] = new_total

            # 기존 order_items 삭제 후 재생성
            await asyncio.to_thread(
                lambda: self.items.delete().eq("order_id", str(order_id)).execute()
            )
            for item in items_payload:
                await asyncio.to_thread(
                    lambda i=item: self.items.insert(
                        {
                            "order_id": str(order_id),
                            "product_id": str(i["product_id"]),
                            "quantity": i["quantity"],
                            "unit_price": i["unit_price"],
                            "subtotal": i["quantity"] * i["unit_price"],
                            "notes": i.get("notes"),
                        }
                    ).execute()
                )

        if update_fields:
            await asyncio.to_thread(
                lambda: self.orders.update(update_fields)
                .eq("id", str(order_id))
                .is_("deleted_at", None)
                .execute()
            )

        updated_order = await self.get_order(order_id)
        if updated_order:
            await self._sync_calendar_events_for_order(updated_order)
            return updated_order
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    async def cancel_order(
        self, order_id: UUID, reason: str, user: dict
    ) -> dict:
        """주문 취소 — 양쪽 모두 가능, COMPLETED 이후 불가. soft delete 와 별개로 이력 보존."""
        order = await self._get_order_or_404(order_id)
        user_id_str = str(user["id"])
        self._assert_participant(order, user_id_str)

        if order["status"] == "COMPLETED":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot cancel a completed order",
            )
        if order["status"] == "CANCELLED":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Order is already cancelled",
            )

        cancelled_at = datetime.now(timezone.utc).isoformat()
        await asyncio.to_thread(
            lambda: self.orders.update(
                {
                    "status": "CANCELLED",
                    "cancellation_reason": reason,
                    "cancelled_at": cancelled_at,
                    "cancelled_by": user_id_str,
                }
            )
            .eq("id", str(order_id))
            .is_("deleted_at", None)
            .execute()
        )
        updated_order = await self.get_order(order_id)
        if updated_order:
            await self._sync_calendar_events_for_order(updated_order)
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found",
            )

        # 채팅에 주문 취소 이벤트 발송
        try:
            room = await self._ensure_chat_room_for_order(order)
            if room:
                await self._emit_chat_event(
                    room=room,
                    sender_id=user_id_str,
                    message_type="ORDER_CANCELLED",
                    content=f"주문 취소: {reason}",
                    metadata={
                        "order_id": str(order_id),
                        "order_number": order.get("order_number"),
                        "reason": reason,
                        "cancelled_by": user_id_str,
                    },
                )
        except Exception as e:
            print(
                f"[order_service.cancel_order] chat event 실패 (무시): "
                f"{type(e).__name__}: {e}"
            )

        return updated_order

    # ===========================================
    # 협상 (counter-offer)
    # ===========================================

    async def submit_counter_offer(
        self, order_id: UUID, payload: dict, user: dict
    ) -> dict:
        """주문이 QUOTE_REQUESTED 또는 NEGOTIATING 상태일 때만 가능. 이전 PENDING은 SUPERSEDED로."""
        order = await self._get_order_or_404(order_id)
        user_id_str = str(user["id"])
        actor_role = self._assert_participant(order, user_id_str)

        if order["status"] not in ("QUOTE_REQUESTED", "NEGOTIATING"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Counter-offer is only allowed in QUOTE_REQUESTED or NEGOTIATING status",
            )

        proposed_items = payload.get("proposed_items")
        proposed_items_json = (
            [
                {
                    "product_id": str(i["product_id"]),
                    "quantity": i["quantity"],
                    "unit_price": i["unit_price"],
                    "notes": i.get("notes"),
                }
                for i in proposed_items
            ]
            if proposed_items
            else None
        )

        # 이전 PENDING 협상가 ID 들을 먼저 조회 (메시지 동기화용)
        prev_pending = await asyncio.to_thread(
            lambda: self.negotiations.select("id")
            .eq("order_id", str(order_id))
            .eq("status", "PENDING")
            .execute()
        )
        superseded_ids: list[str] = [r["id"] for r in (prev_pending.data or [])]

        # 이전 PENDING 협상가 모두 SUPERSEDED 처리
        await asyncio.to_thread(
            lambda: self.negotiations.update({"status": "SUPERSEDED"})
            .eq("order_id", str(order_id))
            .eq("status", "PENDING")
            .execute()
        )

        # 같은 offer_id 를 metadata 에 가진 messages 행들의 status 도 SUPERSEDED 로 동기화
        for prev_id in superseded_ids:
            await self._sync_offer_status_in_messages(prev_id, "SUPERSEDED")

        insert_payload = {
            "order_id": str(order_id),
            "from_user_id": user_id_str,
            "from_role": actor_role,
            "proposed_total_amount": int(payload["proposed_total_amount"]),
            "proposed_items": proposed_items_json,
            "notes": payload.get("notes"),
            "status": "PENDING",
        }
        result = await asyncio.to_thread(
            lambda: self.negotiations.insert(insert_payload).execute()
        )
        new_offer = result.data[0]

        # QUOTE_REQUESTED → NEGOTIATING 자동 전환
        if order["status"] == "QUOTE_REQUESTED":
            await asyncio.to_thread(
                lambda: self.orders.update({"status": "NEGOTIATING"})
                .eq("id", str(order_id))
                .is_("deleted_at", None)
                .execute()
            )
        updated_order = await self.get_order(order_id)
        if updated_order:
            await self._sync_calendar_events_for_order(updated_order)

        # 채팅에 협상가 제시 이벤트 발송
        amount = int(payload["proposed_total_amount"])
        try:
            room = await self._ensure_chat_room_for_order(order)
            if room:
                role_label = "판매자" if actor_role == "SELLER" else "구매자"
                await self._emit_chat_event(
                    room=room,
                    sender_id=user_id_str,
                    message_type="COUNTER_OFFER",
                    content=f"{role_label}이(가) {amount:,}원 제시",
                    metadata={
                        "offer_id": str(new_offer["id"]),
                        "order_id": str(order_id),
                        "proposed_total_amount": amount,
                        "from_role": actor_role,
                        "notes": payload.get("notes"),
                        "status": "PENDING",
                    },
                )
        except Exception as e:
            print(
                f"[order_service.submit_counter_offer] chat event 실패 (무시): "
                f"{type(e).__name__}: {e}"
            )

        # 알림 emit — 상대방에게 (제시자가 아닌 쪽)
        sender_meta = await self._get_user_meta(user_id_str)
        sender_name = (
            sender_meta.get("name")
            or sender_meta.get("company_name")
            or ("판매자" if actor_role == "SELLER" else "구매자")
        )
        await self._emit_order_notification(
            order=order,
            sender_id=user_id_str,
            notif_type="COUNTER_OFFER",
            title="새 가격 제안",
            body=f"{sender_name}님이 {amount:,}원 제안했습니다",
        )

        return new_offer

    async def _get_offer_or_404(self, order_id: UUID, offer_id: UUID) -> dict:
        result = await asyncio.to_thread(
            lambda: self.negotiations.select("*")
            .eq("id", str(offer_id))
            .eq("order_id", str(order_id))
            .execute()
        )
        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Counter-offer not found",
            )
        return result.data[0]

    async def accept_counter_offer(
        self, order_id: UUID, offer_id: UUID, user: dict
    ) -> dict:
        """상대방의 PENDING 협상가만 수락 가능. orders.total_amount, order_items 갱신."""
        order = await self._get_order_or_404(order_id)
        user_id_str = str(user["id"])
        self._assert_participant(order, user_id_str)

        offer = await self._get_offer_or_404(order_id, offer_id)

        if offer["status"] != "PENDING":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot accept offer in {offer['status']} status",
            )
        if offer["from_user_id"] == user_id_str:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot accept your own counter-offer",
            )

        responded_at = datetime.now(timezone.utc).isoformat()

        # 협상가 행 ACCEPTED 처리
        await asyncio.to_thread(
            lambda: self.negotiations.update(
                {
                    "status": "ACCEPTED",
                    "responded_at": responded_at,
                    "responded_by": user_id_str,
                }
            )
            .eq("id", str(offer_id))
            .execute()
        )

        # 같은 offer_id 를 metadata 에 가진 messages 의 status 도 ACCEPTED 로 동기화
        await self._sync_offer_status_in_messages(offer_id, "ACCEPTED")

        # orders.total_amount 갱신
        await asyncio.to_thread(
            lambda: self.orders.update(
                {"total_amount": int(offer["proposed_total_amount"])}
            )
            .eq("id", str(order_id))
            .is_("deleted_at", None)
            .execute()
        )

        # proposed_items가 있으면 order_items 교체
        proposed_items = offer.get("proposed_items")
        if proposed_items:
            await asyncio.to_thread(
                lambda: self.items.delete().eq("order_id", str(order_id)).execute()
            )
            for item in proposed_items:
                await asyncio.to_thread(
                    lambda i=item: self.items.insert(
                        {
                            "order_id": str(order_id),
                            "product_id": str(i["product_id"]),
                            "quantity": int(i["quantity"]),
                            "unit_price": int(i["unit_price"]),
                            "subtotal": int(i["quantity"]) * int(i["unit_price"]),
                            "notes": i.get("notes"),
                        }
                    ).execute()
                )
        updated_order = await self.get_order(order_id)
        if updated_order:
            await self._sync_calendar_events_for_order(updated_order)

        # 채팅에 협상가 수락 이벤트 발송
        accepted_amount = int(offer["proposed_total_amount"])
        try:
            room = await self._ensure_chat_room_for_order(order)
            if room:
                role_label = "구매자" if user_id_str == order["buyer_id"] else "판매자"
                await self._emit_chat_event(
                    room=room,
                    sender_id=user_id_str,
                    message_type="OFFER_ACCEPTED",
                    content=f"{role_label}이(가) {accepted_amount:,}원 수락",
                    metadata={
                        "offer_id": str(offer_id),
                        "order_id": str(order_id),
                        "accepted_amount": accepted_amount,
                        "accepted_by": user_id_str,
                    },
                )
        except Exception as e:
            print(
                f"[order_service.accept_counter_offer] chat event 실패 (무시): "
                f"{type(e).__name__}: {e}"
            )

        # 알림 emit — 제안 발신자(상대방)에게 수락 사실 전달
        sender_meta = await self._get_user_meta(user_id_str)
        sender_name = (
            sender_meta.get("name")
            or sender_meta.get("company_name")
            or ("구매자" if user_id_str == order["buyer_id"] else "판매자")
        )
        await self._emit_order_notification(
            order=order,
            sender_id=user_id_str,
            notif_type="OFFER_ACCEPTED",
            title="가격 제안 수락",
            body=f"{sender_name}님이 가격을 수락했습니다 ({accepted_amount:,}원)",
        )

        # 주문 상태는 NEGOTIATING 유지 (별도 update_status 로 CONFIRMED 진행)
        return await self._get_offer_or_404(order_id, offer_id)

    async def reject_counter_offer(
        self, order_id: UUID, offer_id: UUID, user: dict
    ) -> dict:
        """상대방의 PENDING 협상가만 거절 가능."""
        order = await self._get_order_or_404(order_id)
        user_id_str = str(user["id"])
        self._assert_participant(order, user_id_str)

        offer = await self._get_offer_or_404(order_id, offer_id)

        if offer["status"] != "PENDING":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot reject offer in {offer['status']} status",
            )
        if offer["from_user_id"] == user_id_str:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot reject your own counter-offer",
            )

        responded_at = datetime.now(timezone.utc).isoformat()
        await asyncio.to_thread(
            lambda: self.negotiations.update(
                {
                    "status": "REJECTED",
                    "responded_at": responded_at,
                    "responded_by": user_id_str,
                }
            )
            .eq("id", str(offer_id))
            .execute()
        )

        # 같은 offer_id 를 metadata 에 가진 messages 의 status 도 REJECTED 로 동기화
        await self._sync_offer_status_in_messages(offer_id, "REJECTED")

        # 채팅에 협상가 거절 이벤트 발송
        rejected_amount = int(offer.get("proposed_total_amount") or 0)
        try:
            room = await self._ensure_chat_room_for_order(order)
            if room:
                role_label = "구매자" if user_id_str == order["buyer_id"] else "판매자"
                await self._emit_chat_event(
                    room=room,
                    sender_id=user_id_str,
                    message_type="OFFER_REJECTED",
                    content=f"{role_label}이(가) {rejected_amount:,}원 제안을 거절",
                    metadata={
                        "offer_id": str(offer_id),
                        "order_id": str(order_id),
                        "rejected_amount": rejected_amount,
                        "rejected_by": user_id_str,
                    },
                )
        except Exception as e:
            print(
                f"[order_service.reject_counter_offer] chat event 실패 (무시): "
                f"{type(e).__name__}: {e}"
            )

        # 알림 emit — 제안 발신자(상대방)에게 거절 사실 전달
        sender_meta = await self._get_user_meta(user_id_str)
        sender_name = (
            sender_meta.get("name")
            or sender_meta.get("company_name")
            or ("구매자" if user_id_str == order["buyer_id"] else "판매자")
        )
        await self._emit_order_notification(
            order=order,
            sender_id=user_id_str,
            notif_type="OFFER_REJECTED",
            title="가격 제안 거절",
            body=f"{sender_name}님이 가격 제안을 거절했습니다 ({rejected_amount:,}원)",
        )

        return await self._get_offer_or_404(order_id, offer_id)

    async def list_negotiation_history(
        self, order_id: UUID, user: dict
    ) -> list[dict]:
        """주문 당사자만 조회. created_at DESC 정렬."""
        order = await self._get_order_or_404(order_id)
        user_id_str = str(user["id"])
        self._assert_participant(order, user_id_str)

        result = await asyncio.to_thread(
            lambda: self.negotiations.select("*")
            .eq("order_id", str(order_id))
            .order("created_at", desc=True)
            .execute()
        )
        return result.data or []

    # ===========================================
    # 납품일 변경 (delivery date change)
    # ===========================================

    async def _sync_delivery_date_change_status_in_messages(
        self, change_id: UUID | str, new_status: str
    ) -> None:
        """messages.metadata.change_id 가 일치하는 행들의 metadata.status 동기화.

        납품일 변경 요청이 ACCEPTED/REJECTED/SUPERSEDED 로 전환될 때 호출.
        프론트가 metadata.status === 'PENDING' 일 때만 수락/거절 버튼을 노출하므로
        동기화하지 않으면 stale UI 가 남는다 (negotiation 의 _sync_offer_status_in_messages 패턴).

        실패해도 흐름은 막지 않음 (예외 무시 + 로그).
        """
        change_id_str = str(change_id)
        try:
            rows = await asyncio.to_thread(
                lambda: self.client.table("messages")
                .select("id, metadata")
                .eq("metadata->>change_id", change_id_str)
                .execute()
            )
            for row in rows.data or []:
                meta = dict(row.get("metadata") or {})
                meta["status"] = new_status
                row_id = row["id"]
                await asyncio.to_thread(
                    lambda rid=row_id, m=meta: self.client.table("messages")
                    .update({"metadata": m})
                    .eq("id", rid)
                    .execute()
                )
        except Exception as e:
            print(
                f"[order_service._sync_delivery_date_change_status_in_messages] "
                f"실패 (무시): change_id={change_id_str}, new_status={new_status}, "
                f"error={type(e).__name__}: {e}"
            )

    async def _get_delivery_change_or_404(
        self, order_id: UUID, change_id: UUID
    ) -> dict:
        result = await asyncio.to_thread(
            lambda: self.delivery_date_changes.select("*")
            .eq("id", str(change_id))
            .eq("order_id", str(order_id))
            .execute()
        )
        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Delivery date change request not found",
            )
        return result.data[0]

    async def submit_delivery_date_change(
        self, order_id: UUID, payload: dict, user: dict
    ) -> dict:
        """납품일 변경 요청 — 주문 당사자, QUOTE_REQUESTED/NEGOTIATING/CONFIRMED 상태.

        PREPARING 이상은 이미 출하 준비 중이므로 차단 (도메인 가드).
        이전 PENDING 변경 요청은 SUPERSEDED 처리 + 같은 change_id 의 메시지 metadata.status 동기화.
        proposed_delivery_date 는 오늘 이상이어야 함 (router 단에서 422 검증).
        """
        order = await self._get_order_or_404(order_id)
        user_id_str = str(user["id"])
        actor_role = self._assert_participant(order, user_id_str)

        if order["status"] not in ("QUOTE_REQUESTED", "NEGOTIATING", "CONFIRMED"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Delivery date change is only allowed in "
                    "QUOTE_REQUESTED, NEGOTIATING, or CONFIRMED status"
                ),
            )

        proposed_date = payload["proposed_delivery_date"]
        # date 또는 ISO 문자열로 들어옴 (router model_dump(mode='json') 시 문자열)
        proposed_date_str = (
            proposed_date.isoformat()
            if hasattr(proposed_date, "isoformat")
            else str(proposed_date)[:10]
        )

        # 이전 PENDING 변경 요청 ID 들 조회 (메시지 동기화용)
        prev_pending = await asyncio.to_thread(
            lambda: self.delivery_date_changes.select("id")
            .eq("order_id", str(order_id))
            .eq("status", "PENDING")
            .execute()
        )
        superseded_ids: list[str] = [r["id"] for r in (prev_pending.data or [])]

        # 이전 PENDING 모두 SUPERSEDED 처리
        await asyncio.to_thread(
            lambda: self.delivery_date_changes.update({"status": "SUPERSEDED"})
            .eq("order_id", str(order_id))
            .eq("status", "PENDING")
            .execute()
        )

        # 같은 change_id 를 metadata 에 가진 messages 의 status 도 SUPERSEDED 동기화
        for prev_id in superseded_ids:
            await self._sync_delivery_date_change_status_in_messages(
                prev_id, "SUPERSEDED"
            )

        insert_payload = {
            "order_id": str(order_id),
            "from_user_id": user_id_str,
            "from_role": actor_role,
            "proposed_delivery_date": proposed_date_str,
            "notes": payload.get("notes"),
            "status": "PENDING",
        }
        result = await asyncio.to_thread(
            lambda: self.delivery_date_changes.insert(insert_payload).execute()
        )
        new_change = result.data[0]

        # 채팅에 납품일 변경 요청 이벤트 발송
        try:
            room = await self._ensure_chat_room_for_order(order)
            if room:
                role_label = "판매자" if actor_role == "SELLER" else "구매자"
                content = (
                    f"{role_label}이(가) 납품일을 {proposed_date_str} 로 변경 요청"
                )
                await self._emit_chat_event(
                    room=room,
                    sender_id=user_id_str,
                    message_type="DELIVERY_DATE_CHANGE",
                    content=content,
                    metadata={
                        "change_id": str(new_change["id"]),
                        "order_id": str(order_id),
                        "order_number": order.get("order_number"),
                        "proposed_delivery_date": proposed_date_str,
                        "previous_delivery_date": self._date_only(
                            order.get("delivery_date")
                        ),
                        "from_role": actor_role,
                        "notes": payload.get("notes"),
                        "status": "PENDING",
                    },
                )
        except Exception as e:
            print(
                f"[order_service.submit_delivery_date_change] chat event 실패 "
                f"(무시): {type(e).__name__}: {e}"
            )

        # 알림 emit — 상대방에게 (제시자가 아닌 쪽)
        sender_meta = await self._get_user_meta(user_id_str)
        sender_name = (
            sender_meta.get("name")
            or sender_meta.get("company_name")
            or ("판매자" if actor_role == "SELLER" else "구매자")
        )
        await self._emit_order_notification(
            order=order,
            sender_id=user_id_str,
            notif_type="DELIVERY_DATE_CHANGE",
            title="납품일 변경 요청",
            body=f"{sender_name}님이 {proposed_date_str} 로 변경 요청했습니다",
        )

        return new_change

    async def accept_delivery_date_change(
        self, order_id: UUID, change_id: UUID, user: dict
    ) -> dict:
        """납품일 변경 수락 — 본인이 제시한 PENDING 은 수락 불가 (상대방만).

        orders.delivery_date 갱신 → _sync_calendar_events_for_order 호출 (캘린더 재동기화)
        → messages.metadata.status 동기화 → DELIVERY_DATE_ACCEPTED 채팅 이벤트.
        """
        order = await self._get_order_or_404(order_id)
        user_id_str = str(user["id"])
        self._assert_participant(order, user_id_str)

        change = await self._get_delivery_change_or_404(order_id, change_id)

        if change["status"] != "PENDING":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot accept delivery date change in {change['status']} status",
            )
        if change["from_user_id"] == user_id_str:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot accept your own delivery date change request",
            )

        responded_at = datetime.now(timezone.utc).isoformat()
        proposed_date = change["proposed_delivery_date"]
        proposed_date_str = (
            proposed_date.isoformat()
            if hasattr(proposed_date, "isoformat")
            else str(proposed_date)[:10]
        )

        # 변경 요청 행 ACCEPTED 처리
        await asyncio.to_thread(
            lambda: self.delivery_date_changes.update(
                {
                    "status": "ACCEPTED",
                    "responded_at": responded_at,
                    "responded_by": user_id_str,
                }
            )
            .eq("id", str(change_id))
            .execute()
        )

        # 같은 change_id 를 metadata 에 가진 messages 의 status 도 ACCEPTED 동기화
        await self._sync_delivery_date_change_status_in_messages(
            change_id, "ACCEPTED"
        )

        # orders.delivery_date 갱신 (가장 중요한 부수효과)
        await asyncio.to_thread(
            lambda: self.orders.update({"delivery_date": proposed_date_str})
            .eq("id", str(order_id))
            .is_("deleted_at", None)
            .execute()
        )

        # 캘린더 재동기화 — order 양 당사자의 active calendar_events 가
        # 새 delivery_date 로 옮겨가고 옛 event_date 의 row 는 soft-delete 된다
        # (_sync_calendar_events_for_order_sync 내부 로직)
        updated_order = await self.get_order(order_id)
        if updated_order:
            await self._sync_calendar_events_for_order(updated_order)

        # 채팅에 수락 이벤트 발송
        try:
            room = await self._ensure_chat_room_for_order(order)
            if room:
                role_label = "구매자" if user_id_str == order["buyer_id"] else "판매자"
                await self._emit_chat_event(
                    room=room,
                    sender_id=user_id_str,
                    message_type="DELIVERY_DATE_ACCEPTED",
                    content=(
                        f"{role_label}이(가) 납품일 변경 수락 → {proposed_date_str}"
                    ),
                    metadata={
                        "change_id": str(change_id),
                        "order_id": str(order_id),
                        "order_number": order.get("order_number"),
                        "accepted_delivery_date": proposed_date_str,
                        "previous_delivery_date": self._date_only(
                            order.get("delivery_date")
                        ),
                        "accepted_by": user_id_str,
                    },
                )
        except Exception as e:
            print(
                f"[order_service.accept_delivery_date_change] chat event 실패 "
                f"(무시): {type(e).__name__}: {e}"
            )

        # 알림 emit — 변경 요청 발신자(상대방)에게 수락 사실 전달
        sender_meta = await self._get_user_meta(user_id_str)
        sender_name = (
            sender_meta.get("name")
            or sender_meta.get("company_name")
            or ("구매자" if user_id_str == order["buyer_id"] else "판매자")
        )
        await self._emit_order_notification(
            order=order,
            sender_id=user_id_str,
            notif_type="DELIVERY_DATE_ACCEPTED",
            title="납품일 변경 수락",
            body=f"{sender_name}님이 납품일 변경을 수락했습니다 ({proposed_date_str})",
        )

        return await self._get_delivery_change_or_404(order_id, change_id)

    async def reject_delivery_date_change(
        self, order_id: UUID, change_id: UUID, user: dict
    ) -> dict:
        """납품일 변경 거절 — 본인이 제시한 PENDING 은 거절 불가 (상대방만)."""
        order = await self._get_order_or_404(order_id)
        user_id_str = str(user["id"])
        self._assert_participant(order, user_id_str)

        change = await self._get_delivery_change_or_404(order_id, change_id)

        if change["status"] != "PENDING":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot reject delivery date change in {change['status']} status",
            )
        if change["from_user_id"] == user_id_str:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot reject your own delivery date change request",
            )

        responded_at = datetime.now(timezone.utc).isoformat()
        proposed_date = change["proposed_delivery_date"]
        proposed_date_str = (
            proposed_date.isoformat()
            if hasattr(proposed_date, "isoformat")
            else str(proposed_date)[:10]
        )

        await asyncio.to_thread(
            lambda: self.delivery_date_changes.update(
                {
                    "status": "REJECTED",
                    "responded_at": responded_at,
                    "responded_by": user_id_str,
                }
            )
            .eq("id", str(change_id))
            .execute()
        )

        # 같은 change_id 를 metadata 에 가진 messages 의 status 도 REJECTED 동기화
        await self._sync_delivery_date_change_status_in_messages(
            change_id, "REJECTED"
        )

        # 채팅에 거절 이벤트 발송
        try:
            room = await self._ensure_chat_room_for_order(order)
            if room:
                role_label = "구매자" if user_id_str == order["buyer_id"] else "판매자"
                await self._emit_chat_event(
                    room=room,
                    sender_id=user_id_str,
                    message_type="DELIVERY_DATE_REJECTED",
                    content=(
                        f"{role_label}이(가) 납품일 {proposed_date_str} 변경 요청을 거절"
                    ),
                    metadata={
                        "change_id": str(change_id),
                        "order_id": str(order_id),
                        "order_number": order.get("order_number"),
                        "rejected_delivery_date": proposed_date_str,
                        "rejected_by": user_id_str,
                    },
                )
        except Exception as e:
            print(
                f"[order_service.reject_delivery_date_change] chat event 실패 "
                f"(무시): {type(e).__name__}: {e}"
            )

        # 알림 emit — 변경 요청 발신자(상대방)에게 거절 사실 전달
        sender_meta = await self._get_user_meta(user_id_str)
        sender_name = (
            sender_meta.get("name")
            or sender_meta.get("company_name")
            or ("구매자" if user_id_str == order["buyer_id"] else "판매자")
        )
        await self._emit_order_notification(
            order=order,
            sender_id=user_id_str,
            notif_type="DELIVERY_DATE_REJECTED",
            title="납품일 변경 거절",
            body=f"{sender_name}님이 납품일 변경을 거절했습니다 ({proposed_date_str})",
        )

        return await self._get_delivery_change_or_404(order_id, change_id)

    async def list_delivery_date_changes(
        self, order_id: UUID, user: dict
    ) -> list[dict]:
        """납품일 변경 요청 이력 — 주문 당사자만, created_at DESC (시간 역순).

        from_user_name / from_user_company 를 동적 주입한다 (users 테이블 별도 조회).
        """
        order = await self._get_order_or_404(order_id)
        user_id_str = str(user["id"])
        self._assert_participant(order, user_id_str)

        result = await asyncio.to_thread(
            lambda: self.delivery_date_changes.select("*")
            .eq("order_id", str(order_id))
            .order("created_at", desc=True)
            .execute()
        )
        rows = result.data or []
        if not rows:
            return []

        # from_user_id 별 사용자 정보 일괄 조회 (N+1 회피)
        from_user_ids = list({str(r["from_user_id"]) for r in rows if r.get("from_user_id")})
        users_map: dict[str, dict] = {}
        if from_user_ids:
            users_result = await asyncio.to_thread(
                lambda: self.client.table("users")
                .select("id, name, company_name")
                .in_("id", from_user_ids)
                .execute()
            )
            for u in users_result.data or []:
                users_map[str(u["id"])] = u

        for r in rows:
            u = users_map.get(str(r.get("from_user_id"))) or {}
            r["from_user_name"] = u.get("name")
            r["from_user_company"] = u.get("company_name")
        return rows


order_service = OrderService()
