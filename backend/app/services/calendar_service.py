import asyncio
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from app.core.supabase import get_supabase_client


# ===========================================
# Supabase select 임베딩 (calendar_events join 응답용)
# ===========================================
# order:orders!order_id  : calendar_events.order_id → orders FK 자동 추론
# items:order_items(...) : orders.id ← order_items.order_id 역참조 + product 임베딩
# soft-delete 된 주문/상품은 임베딩 결과가 None 이 되도록 PostgREST 가 처리하지 않으므로,
# flatten 단계에서 deleted_at 가 None 인 row 만 사용한다.
#
# orders.status 도 함께 임베딩해 calendar_events.event_type 이 ORDER 로 고정되어 있어도
# 프론트가 주문 상태별 색상을 칠할 수 있도록 order_status 파생 필드로 노출한다.
CALENDAR_SELECT_WITH_JOINS = (
    "*,"
    "order:orders!order_id("
    "order_number,status,deleted_at,"
    "buyer:users!buyer_id(name,company_name),"
    "seller:users!seller_id(name,company_name),"
    "items:order_items(product:products(name,deleted_at))"
    ")"
)


def _flatten_event_row(row: dict) -> dict:
    """orders/users/order_items/products 임베딩을 flatten.

    부여 필드:
    - order_number, product_name, order_status
    - buyer_name / buyer_company / seller_name / seller_company

    규칙:
    - order_id 가 None  → 위 필드 모두 None
    - 주문이 soft-deleted → 위 필드 모두 None
    - 첫 활성 아이템 product 가 있으면 product_name 사용
    - 활성 아이템이 2개 이상이면 "{첫 상품명} 외 N건"
    - order_status: orders.status 값을 그대로 (QUOTE_REQUESTED, CONFIRMED, ... CANCELLED)
    - buyer/seller: users 임베딩이 None 이면 (사용자 hard-delete 등) 해당 필드만 None
    """
    order_payload = row.pop("order", None)
    row["order_number"] = None
    row["product_name"] = None
    row["order_status"] = None
    row["buyer_name"] = None
    row["buyer_company"] = None
    row["seller_name"] = None
    row["seller_company"] = None

    if not order_payload:
        return row
    if order_payload.get("deleted_at"):
        return row

    row["order_number"] = order_payload.get("order_number")
    row["order_status"] = order_payload.get("status")

    buyer = order_payload.get("buyer") or {}
    seller = order_payload.get("seller") or {}
    row["buyer_name"] = buyer.get("name")
    row["buyer_company"] = buyer.get("company_name")
    row["seller_name"] = seller.get("name")
    row["seller_company"] = seller.get("company_name")

    items = order_payload.get("items") or []
    product_names: list[str] = []
    for item in items:
        product = item.get("product") if isinstance(item, dict) else None
        if not product:
            continue
        if product.get("deleted_at"):
            continue
        name = product.get("name")
        if name:
            product_names.append(name)

    if product_names:
        if len(product_names) == 1:
            row["product_name"] = product_names[0]
        else:
            row["product_name"] = f"{product_names[0]} 외 {len(product_names) - 1}건"
    return row


def _attach_order_payload(row: dict, orders_by_id: dict[str, dict]) -> dict:
    """list_events batch 조회 결과를 _flatten_event_row 와 동일 형태로 합성.

    orders_by_id[order_id] = {
        "order_number": str,
        "status": str,
        "deleted_at": str | None,
        "items": [{"product": {"name": str, "deleted_at": ...}}, ...],
    }
    """
    order_id = row.get("order_id")
    if order_id:
        order_payload = orders_by_id.get(str(order_id))
        # order_payload 가 None 이어도 _flatten_event_row 가 None 처리해줌
        row["order"] = order_payload
    else:
        row["order"] = None
    return _flatten_event_row(row)


class CalendarService:
    def __init__(self):
        # lazy initialization — 모듈 import 시점에 Supabase client 생성하지 않는다.
        # CI/테스트 환경에서 SUPABASE_SERVICE_ROLE_KEY 가 없을 때 import 시점 오류 방지.
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = get_supabase_client()
        return self._client

    @property
    def table(self):
        return self.client.table("calendar_events")

    async def list_events(
        self,
        *,
        user_id: UUID,
        year: Optional[int] = None,
        month: Optional[int] = None,
    ) -> list[dict]:
        """일정 조회 — 3-depth 임베딩 대신 batch 조회로 N+1 회피.

        - year + month 모두 전달 → 해당 월 범위로 필터.
        - year/month 중 하나라도 None → 전체 active 일정 반환 (프론트 우측 패널 용).
          연 단위 단독 조회는 미지원 — month 가 없으면 year 도 무시한다.

        쿼리 횟수: 2회 (calendar_events → orders+order_items+products 임베딩)
        - 이전: 매 호출마다 _ensure_order_events_for_user 가 user 의 모든 주문에 대해
                order_service.sync_calendar_events_for_order_id 를 순차 호출 → N+1 폭주.
                동시 connection 폭주로 ReadError 가 자주 발생하면서도 무시되어
                매 캘린더 GET 마다 N×왕복 시간을 사용자가 기다리던 구조.
        - 이후: order_service 의 모든 mutation (create_order/update_status/update_order/
                cancel_order/submit_counter_offer/accept_counter_offer) 에서 이미
                _sync_calendar_events_for_order 를 호출하므로 calendar_events 는
                항상 최신 상태로 유지된다 → 조회 시점 backfill 불필요.

        - 1차 조회: calendar_events 단순 select (RLS 평가 1회)
        - 2차 조회: order_id 모아 단일 in_() 로 orders + order_items + products 임베딩
                   (3-depth 임베딩 1회보다 RLS 누적이 적어 빠름)
        """
        base = (
            self.table.select("*")
            .eq("user_id", str(user_id))
            .is_("deleted_at", None)
        )

        # year + month 가 모두 있을 때만 월 범위 필터, 아니면 전체 active 일정.
        if year is not None and month is not None:
            start_date = f"{year}-{month:02d}-01"
            if month == 12:
                end_date = f"{year + 1}-01-01"
            else:
                end_date = f"{year}-{month + 1:02d}-01"
            base = base.gte("event_date", start_date).lt("event_date", end_date)

        # 1. calendar_events 만 단순 조회 (임베딩 X)
        events_result = await asyncio.to_thread(
            lambda: base.order("event_date").execute()
        )
        events: list[dict] = events_result.data or []

        # 2. order_id 가 있는 이벤트가 없으면 임베딩 조회 생략
        order_ids = sorted({
            str(row["order_id"]) for row in events if row.get("order_id")
        })
        if not order_ids:
            return [_attach_order_payload(row, {}) for row in events]

        # 3. 해당 주문들을 한 번의 쿼리로 가져오되 order_items + products + users 임베딩 사용
        #    (calendar_events RLS 위에 orders RLS 한 번만 누적 → 3-depth 보다 빠름)
        orders_result = await asyncio.to_thread(
            lambda: self.client.table("orders")
            .select(
                "id,order_number,status,deleted_at,"
                "buyer:users!buyer_id(name,company_name),"
                "seller:users!seller_id(name,company_name),"
                "items:order_items(product:products(name,deleted_at))"
            )
            .in_("id", order_ids)
            .execute()
        )
        orders_by_id: dict[str, dict] = {
            str(o["id"]): o for o in (orders_result.data or [])
        }

        # 4. 방어적 dedupe — DB 가 정상이어도 미래의 race condition 으로 같은
        #    (order_id, event_date) 에 active row 가 2개 이상 잔존할 수 있다.
        #    user_id 동일은 list_events 의 .eq("user_id", ...) 로 보장됨.
        #    manual event(order_id IS NULL) 은 dedupe 대상 제외.
        seen: dict[tuple[str, str], dict] = {}
        manual_events: list[dict] = []
        for row in events:
            order_id_val = row.get("order_id")
            if not order_id_val:
                manual_events.append(row)
                continue
            event_date_val = row.get("event_date")
            key = (str(order_id_val), str(event_date_val)[:10] if event_date_val is not None else "")
            existing = seen.get(key)
            if existing is None:
                seen[key] = row
                continue
            # 더 최신 row 보존 (updated_at DESC, fallback created_at DESC)
            row_ts = (row.get("updated_at") or row.get("created_at") or "")
            existing_ts = (existing.get("updated_at") or existing.get("created_at") or "")
            if row_ts > existing_ts:
                seen[key] = row

        deduped_events = manual_events + list(seen.values())
        return [_attach_order_payload(row, orders_by_id) for row in deduped_events]

    async def _get_event_with_joins(self, event_id: str) -> Optional[dict]:
        """단일 이벤트를 join 임베딩과 함께 조회 후 flatten."""
        result = await asyncio.to_thread(
            lambda: self.table.select(CALENDAR_SELECT_WITH_JOINS)
            .eq("id", event_id)
            .single()
            .execute()
        )
        if not result.data:
            return None
        return _flatten_event_row(result.data)

    async def create_event(self, user_id: UUID, data: dict) -> dict:
        payload = {**data, "user_id": str(user_id)}
        # date/time 객체를 문자열로 변환
        for key in ("event_date", "start_time", "end_time"):
            if key in payload and payload[key] is not None:
                payload[key] = str(payload[key])
        if "order_id" in payload and payload["order_id"] is not None:
            payload["order_id"] = str(payload["order_id"])

        # PostgREST 의 INSERT 응답에 임베딩 트리를 포함시키기 위해
        # 빌더의 query params 에 select 를 직접 주입한다.
        # supabase-py 2.11.0 에는 .insert(...).select(...) 체이닝이 없지만,
        # ?select=... query param + Prefer: return=representation 만 있으면
        # PostgREST 가 INSERT 결과를 임베딩 트리로 돌려준다 → 한 번의 round-trip.
        builder = self.table.insert(payload)
        builder.params = builder.params.set("select", CALENDAR_SELECT_WITH_JOINS)
        result = await asyncio.to_thread(lambda: builder.execute())

        if not result.data:
            return {
                "order_number": None,
                "product_name": None,
                "order_status": None,
            }
        return _flatten_event_row(result.data[0])

    async def update_event(
        self, event_id: UUID, user_id: UUID, data: dict
    ) -> Optional[dict]:
        update_data = {k: v for k, v in data.items() if v is not None}
        for key in ("event_date", "start_time", "end_time"):
            if key in update_data:
                update_data[key] = str(update_data[key])

        if not update_data:
            return None

        # INSERT 와 동일하게 UPDATE 응답에도 임베딩 트리 포함시켜 round-trip 1회로 단축
        builder = (
            self.table.update(update_data)
            .eq("id", str(event_id))
            .eq("user_id", str(user_id))
        )
        builder.params = builder.params.set("select", CALENDAR_SELECT_WITH_JOINS)
        result = await asyncio.to_thread(lambda: builder.execute())

        if not result.data:
            return None
        return _flatten_event_row(result.data[0])

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
