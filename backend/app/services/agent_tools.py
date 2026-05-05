"""Deprecated re-export shim — 도구는 backend/app/services/agent/tools/ 로 이동.

이 파일은 chat_ws.py / orchestrator.py / 기타 외부 코드의 backward compat 을
유지하기 위해 남아있다. 옮긴 도구들은 `from app.services.agent.tools.<domain>` 에서
직접 import 해도 동일한 함수 객체를 가져올 수 있다 (re-export).

남는 책임:
1. 옮긴 37 개 도구 함수 re-export (chat_ws.py / 외부 호출 호환).
2. 아직 도메인 모듈로 옮기지 않은 cross-domain helper 들의 단일 정의 위치.
   (`_UUID_PATTERN`, `_run_async_in_thread`, `_service_error_payload`,
    `_sync_calendar_events_for_order_id`, `_find_seller_by_name`,
    `_find_product_by_name`, `_deduct_seller_stock_for_order` 등)
3. 아직 옮기지 않은 4 개 도구 (chat 3 + subscription 1) 의 본문.
4. `analyze_chat_consensus` (chat_ws.py 가 직접 import; TOOL_FUNCTION_MAP 미등록).
5. `TOOL_FUNCTION_MAP` — registry + 잔존 4개 통합본 (orchestrator import 호환).

PR 3 에서 chat 도메인 모듈을 신설해 잔존 4개를 마저 옮긴 뒤,
PR 4 에서 이 파일과 cross-domain helper 를 `agent/_shared.py` 로 이동하고
shim 자체를 제거할 예정이다.
"""

import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Optional

from app.core.supabase import get_supabase_client

# ─────────────────────────────────────────────
# (1) 옮긴 37개 도구 함수 re-export
# ─────────────────────────────────────────────
# 외부 코드(chat_ws.py / 옛 import)가 `from app.services.agent_tools import
# <name>` 형태로 사용하던 함수들을 동일 위치에서 노출한다. 도메인 모듈에서
# @tool 데코레이터로 등록한 함수 그대로이며, 이 import 자체로 ToolRegistry
# 등록도 트리거된다.

from app.services.agent.tools.product import (  # noqa: F401
    get_products,
    check_stock,
    update_stock,
    create_product,
    delete_product,
    update_product,
)
from app.services.agent.tools.order import (  # noqa: F401
    get_orders,
    get_order_detail,
    update_order_status,
    update_order,
    create_order,
    delete_order,
)
from app.services.agent.tools.partner import (  # noqa: F401
    find_alternative_partners,
    request_partner_registration,
    request_partner_registration_by_name,
    get_incoming_partner_requests,
    accept_partner_request,
    reject_partner_request,
    get_partners,
)
from app.services.agent.tools.subscription import (  # noqa: F401
    create_subscription_request,
    accept_subscription_request,
    reject_subscription_request,
    create_subscription_from_order,
)
from app.services.agent.tools.negotiation import (  # noqa: F401
    submit_counter_offer,
    accept_counter_offer,
    reject_counter_offer,
    submit_delivery_date_change,
    accept_delivery_date_change,
    reject_delivery_date_change,
)
from app.services.agent.tools.user import (  # noqa: F401
    get_user_profile,
    find_sellers_by_product,
    find_buyers_by_product,
    open_chat_room,
)
from app.services.agent.tools.calendar import (  # noqa: F401
    get_calendar_events,
    create_calendar_event,
    update_calendar_event,
    delete_calendar_event,
)


# ─────────────────────────────────────────────
# (2) Cross-domain helper — 도메인 모듈이 lazy import 로 사용
# ─────────────────────────────────────────────
# 이 helper 들은 `from app.services.agent_tools import _xxx` 형태로
# `agent.tools.*` 모듈에서 lazy import 된다. 옮기는 시점은 PR 4 (helper 통합).

_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)


def _sync_calendar_events_for_order_id(order_id: str) -> None:
    from app.services.order_service import order_service

    order_service.sync_calendar_events_for_order_id(order_id)


def _find_seller_by_name(supabase, seller_name: str) -> dict:
    """판매자 이름 또는 회사명으로 users 테이블에서 SELLER를 검색한다.

    반환:
      {"found": True, "id": "uuid", ...}                — 1건 정확 매칭
      {"found": False, "candidates": [...]}              — 0건 또는 2건 이상
    """
    result = (
        supabase.table("users")
        .select("id, name, company_name")
        .or_(f"name.ilike.%{seller_name}%,company_name.ilike.%{seller_name}%")
        .eq("role", "SELLER")
        .is_("deleted_at", None)
        .limit(5)
        .execute()
    )
    rows = result.data or []
    if not rows:
        return {"found": False, "candidates": []}

    # 완전 일치 우선
    for row in rows:
        if row.get("name") == seller_name or row.get("company_name") == seller_name:
            return {"found": True, **row}

    if len(rows) == 1:
        return {"found": True, **rows[0]}

    # 여러 명 매칭 — 호출자가 사용자에게 후보 목록을 보여줄 수 있도록 반환
    return {
        "found": False,
        "candidates": [
            {"id": r["id"], "name": r.get("name"), "company_name": r.get("company_name")}
            for r in rows
        ],
    }


def _find_product_by_name(supabase, product_name: str, seller_id: str = "") -> Optional[dict]:
    """
    product_name으로 상품을 검색한다.
    1차: 전체 문자열 ilike 검색
    2차: 실패 시 각 글자를 한 개씩 포함하는 검색으로 fallback (LLM 철자 오류 대응)
    반환: {"id": ..., "name": ...} 또는 None

    NOTE: 동일 함수가 `app.services.agent.tools.product` 에도 존재한다 (도메인
    helper). product 도메인 모듈은 자기 자신의 _find_product_by_name 을 사용하지만,
    `order` / `subscription` 등 다른 도메인 모듈은 `from .product import
    _find_product_by_name` 으로 가져간다. 이 모듈의 정의는 외부 코드가 옛 import
    경로 (`from app.services.agent_tools import _find_product_by_name`) 를 쓸 때를
    위한 호환용.
    """
    def _query(pattern):
        q = (
            supabase.table("products")
            .select("id, name")
            .ilike("name", pattern)
            .is_("deleted_at", None)
        )
        if seller_id:
            q = q.eq("seller_id", seller_id)
        return q.execute()

    # 1차: 그대로 검색
    result = _query(f"%{product_name}%")
    if result.data:
        return result.data[0]

    # 2차 fallback: 각 글자를 개별 검색해서 결과 합산 후 가장 많이 매칭된 것 선택
    match_counts: dict[str, dict] = {}
    for char in product_name:
        if len(char.strip()) == 0:
            continue
        r = _query(f"%{char}%")
        for row in (r.data or []):
            pid = row["id"]
            if pid not in match_counts:
                match_counts[pid] = {"id": pid, "name": row["name"], "count": 0}
            match_counts[pid]["count"] += 1

    if not match_counts:
        return None

    # 가장 많이 매칭된 상품 반환
    best = max(match_counts.values(), key=lambda x: x["count"])
    return {"id": best["id"], "name": best["name"]}


def _deduct_seller_stock_for_order(supabase, order_id: str) -> dict:
    """
    주문이 CONFIRMED 상태로 확정될 때 판매자 재고를 차감한다.
    orders.inventory_deducted_at 값으로 중복 차감을 방지한다.
    """
    try:
        # 1. 주문 조회: 이미 재고 차감된 주문인지 확인
        order_result = (
            supabase.table("orders")
            .select("id, inventory_deducted_at")
            .eq("id", order_id)
            .is_("deleted_at", None)
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
        items_result = (
            supabase.table("order_items")
            .select("id, product_id, quantity")
            .eq("order_id", order_id)
            .execute()
        )

        order_items = items_result.data or []

        if not order_items:
            return {
                "success": False,
                "error": "주문 항목이 없어 재고를 차감할 수 없습니다.",
            }

        # 3. 모든 상품 재고가 충분한지 먼저 검사
        #    중간에 하나라도 부족하면 아무 상품도 차감하지 않기 위함
        stock_checks = []

        for item in order_items:
            product_id = item.get("product_id")
            quantity = item.get("quantity")

            if not product_id or quantity is None:
                return {
                    "success": False,
                    "error": "주문 항목에 product_id 또는 quantity가 없습니다.",
                }

            product_result = (
                supabase.table("products")
                .select("id, name, stock_quantity, status")
                .eq("id", product_id)
                .is_("deleted_at", None)
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
                "product_id": product_id,
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

            supabase.table("products").update({
                "stock_quantity": new_stock,
                "status": new_status,
            }).eq("id", stock["product_id"]).execute()

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

        supabase.table("orders").update({
            "inventory_deducted_at": now_utc,
        }).eq("id", order_id).execute()

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


def _run_async_in_thread(coro_fn):
    """async coroutine 함수를 새 thread + 새 event loop 에서 실행하고 결과 반환.

    coro_fn: 인자 없는 async 함수 (lambda 또는 async def). thread 내에서 새 loop 를
    만들어 실행하므로 호출자가 이미 async 컨텍스트 안에 있어도 안전하다.
    """
    import concurrent.futures

    def _runner():
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(coro_fn())
        finally:
            loop.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_runner)
        return future.result()


def _service_error_payload(exc: Exception) -> dict:
    """order_service 가 raise 한 HTTPException 등을 도구 응답 dict 로 변환."""
    from fastapi import HTTPException as _HTTPException
    if isinstance(exc, _HTTPException):
        return {
            "success": False,
            "error": str(exc.detail),
            "code": exc.status_code,
        }
    return {"success": False, "error": f"{type(exc).__name__}: {exc}"}


# ─────────────────────────────────────────────
# (3) 채팅 도구 — PR 3 에서 chat 도메인 모듈로 이동 예정
# ─────────────────────────────────────────────

def get_chat_rooms(user_id: str) -> dict:
    """사용자가 참여 중인 채팅방 목록을 조회한다."""
    try:
        supabase = get_supabase_client()

        # 사용자가 구매자 혹은 판매자인 채팅방을 모두 가져옴
        result = (
            supabase.table("chat_rooms")
            .select(
                "id, order_id, last_message, created_at, last_message_at, "
                "buyer:users!buyer_id(name, company_name), "
                "seller:users!seller_id(name, company_name), "
                "orders("
                "id, order_number, status, total_amount, created_at, "
                "order_items(quantity, unit_price, products(name, unit))"
                ")"
            )
            .or_(f"buyer_id.eq.{user_id},seller_id.eq.{user_id}")
            .order("last_message_at", desc=True)
            .execute()
        )

        rooms = result.data or []
        flattened = []

        for r in rooms:
            buyer = r.get("buyer") or {}
            seller = r.get("seller") or {}
            order = r.get("orders") or {}

            items = order.get("order_items") if isinstance(order, dict) else []
            items = items or []

            product_names: list[str] = []
            item_summaries: list[str] = []

            primary_product_name = None
            primary_quantity = None
            primary_unit_price = None

            for idx, item in enumerate(items):
                product = item.get("products") if isinstance(item, dict) else None
                product = product or {}

                name = product.get("name")
                unit = product.get("unit") or "kg"
                quantity = item.get("quantity")
                unit_price = item.get("unit_price")

                if name:
                    product_names.append(name)

                if name and quantity is not None and unit_price is not None:
                    item_summaries.append(f"{name} {quantity}{unit} x {unit_price:,}원")
                elif name and quantity is not None:
                    item_summaries.append(f"{name} {quantity}{unit}")
                elif name:
                    item_summaries.append(name)

                if idx == 0:
                    primary_product_name = name
                    primary_quantity = quantity
                    primary_unit_price = unit_price

            if not product_names:
                product_summary = None
            elif len(product_names) == 1:
                product_summary = product_names[0]
            else:
                product_summary = f"{product_names[0]} 외 {len(product_names) - 1}건"

            flattened.append({
                "room_id": r["id"],
                "order_id": r.get("order_id"),
                "last_message": r.get("last_message"),
                "created_at": r.get("created_at"),
                "last_message_at": r.get("last_message_at"),

                "buyer_name": buyer.get("name"),
                "buyer_company": buyer.get("company_name"),
                "seller_name": seller.get("name"),
                "seller_company": seller.get("company_name"),

                "order_number": order.get("order_number") if isinstance(order, dict) else None,
                "order_status": order.get("status") if isinstance(order, dict) else None,
                "order_total_amount": order.get("total_amount") if isinstance(order, dict) else None,

                "product_summary": product_summary,
                "primary_product_name": primary_product_name,
                "primary_quantity": primary_quantity,
                "primary_unit_price": primary_unit_price,
                "item_summary": ", ".join(item_summaries) if item_summaries else None,
            })

        return {
            "success": True,
            "rooms": flattened,
            "count": len(flattened),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "rooms": [], "count": 0}


def get_chat_messages(room_id: str, limit: int = 20) -> dict:
    """특정 채팅방의 최근 대화 내용을 불러온다."""
    try:
        supabase = get_supabase_client()
        result = (
            supabase.table("messages")
            .select("sender_id, content, created_at, sender:users!sender_id(name)")
            .eq("room_id", room_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )

        # 최신순으로 가져온 뒤 시간순(과거->현재)으로 뒤집기
        messages = list(reversed(result.data or []))

        return {
            "success": True,
            "messages": messages,
            "count": len(messages)
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _resolve_chat_room_candidates(
    *,
    sender_id: str,
    partner_user_id: str,
    order_hint: Optional[dict] = None,
) -> list[dict]:
    """sender_id 와 partner_user_id 사이의 활성 채팅방 후보를 찾는다.

    검색 정책:
      - chat_rooms WHERE (seller_id == sender AND buyer_id == partner) OR (seller_id == partner AND buyer_id == sender)
      - chat_rooms 자체에는 deleted_at 컬럼이 없다 (운영 DB 정합 — SKILL_DB.md 참고)
      - order_hint(product_name/quantity/status) 가 있으면 orders 임베딩으로 추가 좁힘
      - recent=true 면 last_message_at DESC + (없으면) created_at DESC 로 가장 최근 1건만 반환

    반환 후보 dict 형식:
      {
        "room_id": str,
        "order_id": str | None,
        "order_number": str | None,
        "order_status": str | None,
        "product_name": str | None,
        "quantity": int | None,
        "unit": str | None,
        "last_message_at": str | None,
        "created_at": str | None,
      }
    """
    supabase = get_supabase_client()

    # chat_rooms + 임베딩 (orders + order_items + products)
    # 양방향 매칭을 위해 or_ 사용. UUID 만 들어가므로 인용 불필요 (SKILL_DB.md 검증 패턴).
    or_clause = (
        f"and(seller_id.eq.{sender_id},buyer_id.eq.{partner_user_id}),"
        f"and(seller_id.eq.{partner_user_id},buyer_id.eq.{sender_id})"
    )

    rooms_query = (
        supabase.table("chat_rooms")
        .select(
            "id, order_id, last_message_at, created_at, seller_id, buyer_id, "
            "orders("
            "id, order_number, status, deleted_at, "
            "order_items(quantity, products(name, unit, deleted_at))"
            ")"
        )
        .or_(or_clause)
        .order("last_message_at", desc=True)
        .order("created_at", desc=True)
    )
    rooms_result = rooms_query.execute()
    rooms = rooms_result.data or []

    hint = order_hint or {}
    hint_product_name = (hint.get("product_name") or "").strip().lower()
    hint_quantity = hint.get("quantity")
    hint_status = (hint.get("status") or "").strip().upper()
    recent_only = bool(hint.get("recent", False))

    candidates: list[dict] = []
    for room in rooms:
        order = room.get("orders") if isinstance(room.get("orders"), dict) else None
        # 주문이 soft-delete 되었거나 CANCELLED 인 방은 후보에서 제외 (정상 거래만)
        if order:
            if order.get("deleted_at") is not None:
                # 주문 자체가 삭제됨 → 일반 채팅방처럼 취급 (order 정보 무시)
                order = None

        # status hint 가 있으면 일치하는 방만
        if hint_status:
            if not order or (order.get("status") or "").upper() != hint_status:
                continue

        # 상품 정보 추출 (활성 상품 중 첫 번째)
        product_name: Optional[str] = None
        product_unit: Optional[str] = None
        primary_quantity: Optional[int] = None
        if order:
            items = order.get("order_items") or []
            for item in items:
                product = item.get("products") if isinstance(item, dict) else None
                if not product:
                    continue
                if product.get("deleted_at") is not None:
                    continue
                product_name = product.get("name")
                product_unit = product.get("unit")
                primary_quantity = item.get("quantity")
                break

        # product_name hint — 부분 일치 (대소문자 무시)
        if hint_product_name:
            if not product_name or hint_product_name not in product_name.lower():
                continue

        # quantity hint — 정확 일치
        if hint_quantity is not None:
            try:
                hint_qty_int = int(hint_quantity)
            except (TypeError, ValueError):
                hint_qty_int = None
            if hint_qty_int is None or primary_quantity != hint_qty_int:
                continue

        candidates.append({
            "room_id": room["id"],
            "order_id": room.get("order_id"),
            "order_number": order.get("order_number") if order else None,
            "order_status": order.get("status") if order else None,
            "product_name": product_name,
            "quantity": primary_quantity,
            "unit": product_unit,
            "last_message_at": room.get("last_message_at"),
            "created_at": room.get("created_at"),
        })

    if recent_only and candidates:
        # 이미 last_message_at DESC 정렬이므로 첫 번째만
        return candidates[:1]

    return candidates


def send_chat_message(
    room_id: str = "",
    sender_id: str = "",
    content: str = "",
    partner_user_id: str = "",
    order_hint: Optional[dict] = None,
    message: str = "",
) -> dict:
    """채팅방에 새 메시지를 전송한다.

    호환 시그니처 (V1: 단일 room_id, V2: partner_user_id + 옵션 hint).
      - V1 (legacy): room_id + sender_id + content → 그대로 전송
      - V2 (신규): partner_user_id + (선택) order_hint + message → 후보 방 자동 탐색
        - 후보 1개: 즉시 전송 (matched_room 정보 함께 반환)
        - 후보 2+개: needs_confirmation=True + 후보 리스트 반환 (전송 안 함)
        - 후보 0개: order_id IS NULL 일반 채팅방으로 fallback. 그것도 없으면 명시적 에러.

    파라미터:
      - room_id: 채팅방 UUID. 명시되면 V1 로 동작 (hint/partner 무시).
      - sender_id: 발신자 UUID. orchestrator `_fix_id_params` 가 항상 현재 user_id 로 강제 주입.
      - content: 메시지 본문 (legacy alias).
      - partner_user_id: 거래처(상대방) 사용자 UUID. V2 진입 조건.
      - order_hint: {product_name?, quantity?, status?, recent?} — 후보 방 좁힘용.
      - message: 메시지 본문 (V2 규약). content 와 message 둘 다 들어오면 message 우선.

    반환:
      - 단일 매칭 + 전송 성공: {success: True, room_id, matched_room: {...}, sent_at, message}
      - 다중 매칭 (전송 보류): {success: False, needs_confirmation: True, candidates: [...], message_preview}
      - 0건 + fallback 일반 방 발송: {success: True, room_id, fallback: "general_room", sent_at, ...}
      - 0건 + 일반 방 없음: {success: False, error: "no_chat_room", ...}
      - 검증 실패: {success: False, error: ...}
    """
    # message 가 우선, 없으면 content (legacy)
    body_text = (message or content or "").strip()
    if not body_text:
        return {"success": False, "error": "메시지 본문이 비어 있습니다."}

    # 발신자 검증
    sender_clean = (sender_id or "").strip()
    if not sender_clean or not _UUID_PATTERN.match(sender_clean):
        return {
            "success": False,
            "error": "invalid_sender_id",
            "message": "발신자 UUID 가 유효하지 않습니다.",
        }

    try:
        supabase = get_supabase_client()

        # ── V1: room_id 직접 지정 → 그대로 전송 ───────────────────────────
        room_clean = (room_id or "").strip()
        if room_clean and _UUID_PATTERN.match(room_clean):
            return _do_send_chat_message(
                supabase=supabase,
                room_id=room_clean,
                sender_id=sender_clean,
                content=body_text,
                matched_info=None,
            )

        # ── V2: partner_user_id 기반 자동 탐색 ────────────────────────────
        partner_clean = (partner_user_id or "").strip()
        if not partner_clean or not _UUID_PATTERN.match(partner_clean):
            return {
                "success": False,
                "error": "missing_room_or_partner",
                "message": "room_id 또는 partner_user_id 중 하나는 반드시 필요합니다.",
            }

        if sender_clean == partner_clean:
            return {
                "success": False,
                "error": "self_chat_not_allowed",
                "message": "자기 자신에게는 메시지를 보낼 수 없습니다.",
            }

        candidates = _resolve_chat_room_candidates(
            sender_id=sender_clean,
            partner_user_id=partner_clean,
            order_hint=order_hint,
        )

        # 1개: 즉시 발송
        if len(candidates) == 1:
            picked = candidates[0]
            return _do_send_chat_message(
                supabase=supabase,
                room_id=picked["room_id"],
                sender_id=sender_clean,
                content=body_text,
                matched_info=picked,
            )

        # 2+ 개: 발송 보류, 사용자 확인 필요 (success=False 로 chat_node 조기 종료 방지)
        if len(candidates) >= 2:
            return {
                "success": False,
                "needs_confirmation": True,
                "candidates": candidates,
                "message_preview": body_text,
                "message": (
                    f"보낼 채팅방 후보가 {len(candidates)}건 있습니다. "
                    "어디로 보낼지 사용자에게 확인 후 room_id 를 직접 지정해 다시 호출하세요."
                ),
            }

        # 0건: order_id IS NULL 인 일반 채팅방으로 fallback
        general_or = (
            f"and(seller_id.eq.{sender_clean},buyer_id.eq.{partner_clean}),"
            f"and(seller_id.eq.{partner_clean},buyer_id.eq.{sender_clean})"
        )
        general_result = (
            supabase.table("chat_rooms")
            .select("id, order_id")
            .or_(general_or)
            .is_("order_id", None)
            .limit(1)
            .execute()
        )
        general_rooms = general_result.data or []
        if general_rooms:
            picked_id = general_rooms[0]["id"]
            return _do_send_chat_message(
                supabase=supabase,
                room_id=picked_id,
                sender_id=sender_clean,
                content=body_text,
                matched_info={
                    "room_id": picked_id,
                    "order_id": None,
                    "order_number": None,
                    "order_status": None,
                    "product_name": None,
                    "quantity": None,
                    "unit": None,
                    "fallback": "general_room",
                },
            )

        return {
            "success": False,
            "error": "no_chat_room",
            "message": (
                "해당 거래처와 연결된 채팅방이 없습니다. "
                "open_chat_room 으로 먼저 채팅방을 생성한 뒤 다시 시도하세요."
            ),
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def _do_send_chat_message(
    *,
    supabase,
    room_id: str,
    sender_id: str,
    content: str,
    matched_info: Optional[dict] = None,
) -> dict:
    """단일 채팅방에 메시지를 INSERT 하고 chat_rooms.last_message 를 갱신한다."""
    try:
        msg_result = (
            supabase.table("messages")
            .insert({"room_id": room_id, "sender_id": sender_id, "content": content})
            .execute()
        )

        # chat_rooms.last_message 업데이트 (목록에서 바로 보이게)
        supabase.table("chat_rooms").update({"last_message": content}).eq("id", room_id).execute()

        result: dict = {
            "success": True,
            "room_id": room_id,
            "message": "메시지가 전송되었습니다.",
            "sent_at": msg_result.data[0]["created_at"] if msg_result.data else None,
        }
        if matched_info:
            result["matched_room"] = matched_info
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


# ─────────────────────────────────────────────
# (4) 캘린더 도구 — PR 2 에서 agent.tools.calendar 로 이동 완료
# ─────────────────────────────────────────────
# 4 개 함수 (get/create/update/delete_calendar_event) 의 본문은
# `app.services.agent.tools.calendar` 모듈로 이동했다. 이 파일 상단의
# `from ...calendar import ...` re-export 로 backward compat 유지.
# ToolRegistry 가 자동으로 TOOL_FUNCTION_MAP / TOOLS_CALENDAR 에 노출.


# ─────────────────────────────────────────────
# (5) 채팅 합의 감지 (chat_ws.py 전용 — TOOL_FUNCTION_MAP 미등록)
# ─────────────────────────────────────────────

CONSENSUS_SYSTEM_PROMPT = """
당신은 농산물 B2B 거래 채팅의 협상 분석 에이전트입니다.
최근 대화를 분석하여 거래 합의 여부와 상태를 JSON으로 반환하십시오.

⚠️ AgenticPay 논문(Structured Action Extraction) 기반 구현.
합의 감지 시 프론트엔드 채팅방에 "AI가 거래 합의를 감지했습니다 (AgenticPay 기반)" 시스템 메시지 표시.

[분류 기준]
- "consensus": 가격, 수량, 납기일 세 가지가 모두 명확히 합의된 경우
  (하나라도 null이면 confidence 낮게 — 단, confidence 무관하게 자동 주문 생성)
- "negotiating": 협상 진행 중
- "rejected": 한쪽이 명확히 거절 또는 협상 종료 의사 표명
- "general": 거래 무관 일상 대화

[합의 표현] "좋습니다", "확인했습니다", "진행하겠습니다", "네 그렇게 하죠", "알겠습니다"
[거절 표현] "어렵겠습니다", "다음에", "조건이 안 맞네요", "힘들 것 같습니다"

[Few-shot 예시 1 — consensus]
대화: 구매자: 사과 100박스 3,000원? / 판매자: 네 가능합니다 / 구매자: 4월 20일 납품 / 판매자: 확인했습니다
반환: {"status":"consensus","confidence":0.97,"extracted":{"product":"사과 후지","quantity":100,"unit":"box","price_per_unit":3000,"delivery_date":"2026-04-20"}}

[Few-shot 예시 2 — consensus 낮음]
대화: 구매자: 배추 좀 보내주세요, 2,500원이요 / 판매자: 네 알겠습니다
반환: {"status":"consensus","confidence":0.61,"extracted":{"product":"배추","quantity":null,"unit":null,"price_per_unit":2500,"delivery_date":null}}

[Few-shot 예시 3 — negotiating]
대화: 구매자: 딸기 50박스? / 판매자: 8,000원입니다 / 구매자: 7,500원은?
반환: {"status":"negotiating","confidence":null,"extracted":{}}

[Few-shot 예시 4 — rejected]
대화: 구매자: 감자 200박스 이번 주? / 판매자: 재고 없어서 어렵겠습니다
반환: {"status":"rejected","confidence":null,"extracted":{"product":"감자","rejection_reason":"재고 없음"}}

[Few-shot 예시 5 — general]
대화: 판매자: 오늘 날씨 좋네요 / 구매자: 그러게요
반환: {"status":"general","confidence":null,"extracted":{}}

반드시 위 JSON 형식으로만 반환. 다른 텍스트 포함 금지.
"""

_CONSENSUS_FALLBACK = {
    "status": "general",
    "confidence": None,
    "extracted": {
        "product": "",
        "quantity": None,
        "unit": None,
        "price_per_unit": None,
        "delivery_date": None,
        "buyer_id": "",
        "seller_id": "",
    },
}


def analyze_chat_consensus(
    room_id: str,
    last_n_messages: int = 10,
    caller_user_id: str | None = None,
) -> dict:
    """
    채팅방 최근 메시지 분석 → 거래 합의 여부 판단.
    동기 함수. asyncio.run 사용 금지 (이벤트루프 충돌).
    chat_ws.py에서 asyncio.to_thread()로 호출.

    권한 검증:
    - caller_user_id 가 주어지면 chat_room 의 buyer_id/seller_id 와 일치하는지 확인
    - 불일치 시 fallback (general) 반환 + 로그 — 합의 자동 처리 차단

    반환:
    {
        "status": "consensus" | "negotiating" | "rejected" | "general",
        "confidence": float | None,
        "extracted": {
            "product": str,
            "quantity": int | None,
            "unit": str | None,
            "price_per_unit": int | None,
            "delivery_date": str | None,  # YYYY-MM-DD
            "buyer_id": str,
            "seller_id": str,
        }
    }
    """
    import copy
    from app.core.config import settings
    fallback = copy.deepcopy(_CONSENSUS_FALLBACK)

    try:
        if not settings.OPENAI_API_KEY:
            return fallback

        supabase = get_supabase_client()

        # 1. messages 테이블에서 최근 N건 조회 (created_at desc → reverse)
        msgs_result = (
            supabase.table("messages")
            .select("sender_id, content, created_at")
            .eq("room_id", room_id)
            .order("created_at", desc=True)
            .limit(last_n_messages)
            .execute()
        )
        messages_raw = list(reversed(msgs_result.data or []))
        if not messages_raw:
            return fallback

        # 2. chat_rooms에서 buyer_id, seller_id 조회
        room_result = (
            supabase.table("chat_rooms")
            .select("buyer_id, seller_id")
            .eq("id", room_id)
            .single()
            .execute()
        )
        if not room_result.data:
            return fallback

        buyer_id = str(room_result.data["buyer_id"])
        seller_id = str(room_result.data["seller_id"])

        # 권한 검증 — caller_user_id 가 채팅방 참여자가 아니면 차단
        if caller_user_id is not None and str(caller_user_id) not in (buyer_id, seller_id):
            print(
                f"[analyze_chat_consensus] 권한 불일치: caller={caller_user_id}, "
                f"buyer={buyer_id}, seller={seller_id} → general fallback"
            )
            return fallback

        # 3. 메시지를 buyer/seller 레이블 + 내용 형식으로 정리
        lines = []
        for msg in messages_raw:
            sender = str(msg.get("sender_id", ""))
            content = msg.get("content", "")
            if sender == buyer_id:
                label = "[구매자]"
            elif sender == seller_id:
                label = "[판매자]"
            else:
                label = "[시스템]"
            lines.append(f"{label} {content}")
        conversation_text = "\n".join(lines)

        # 4. OpenAI 동기 클라이언트로 분석 (response_format=json_object)
        from app.core.llm import get_openai_sync_client
        client = get_openai_sync_client()

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": CONSENSUS_SYSTEM_PROMPT},
                {"role": "user", "content": conversation_text},
            ],
            temperature=0,
        )

        raw_json = response.choices[0].message.content or "{}"
        parsed = json.loads(raw_json)

        # 5. buyer_id / seller_id는 chat_room 정보로 항상 채워서 반환
        extracted = parsed.get("extracted") or {}
        if not isinstance(extracted, dict):
            extracted = {}
        extracted["buyer_id"] = buyer_id
        extracted["seller_id"] = seller_id

        return {
            "status": parsed.get("status", "general"),
            "confidence": parsed.get("confidence"),
            "extracted": extracted,
        }

    except Exception as e:
        print(f"[analyze_chat_consensus] 오류 (fallback 반환): {type(e).__name__}: {e}")
        fallback["extracted"]["buyer_id"] = ""
        fallback["extracted"]["seller_id"] = ""
        return fallback


# ─────────────────────────────────────────────
# (6) 정기배송 — 들어온 PENDING 요청 조회 (도메인 모듈 미이동)
# ─────────────────────────────────────────────
# create/accept/reject_subscription_request 와 create_subscription_from_order
# 는 agent.tools.subscription 으로 이동했지만,
# get_incoming_subscription_requests 는 PR 1 범위가 아니라 여기에 남아있다.

def get_incoming_subscription_requests(user_id: str) -> dict:
    """내게 들어온 PENDING 정기배송 요청 목록을 반환한다 (내가 만들지 않은 것)."""
    user_clean = (user_id or "").strip()
    if not user_clean or not _UUID_PATTERN.match(user_clean):
        return {"success": False, "error": "invalid_user_id"}
    try:
        supabase = get_supabase_client()
        result = supabase.table("subscriptions") \
            .select("id, seller_id, buyer_id, created_by, frequency, start_date, status, notes, subscription_items(product_id, quantity, unit_price, unit)") \
            .eq("status", "PENDING") \
            .neq("created_by", user_clean) \
            .is_("deleted_at", None) \
            .or_(f"seller_id.eq.{user_clean},buyer_id.eq.{user_clean}") \
            .execute()
        requests = []
        for row in (result.data or []):
            counterpart_id = row["buyer_id"] if row["seller_id"] == user_clean else row["seller_id"]
            raw_items = row.get("subscription_items", []) or []
            enriched_items = []
            for item in raw_items:
                pid = item.get("product_id")
                product_name = None
                if pid:
                    try:
                        pr = supabase.table("products").select("name").eq("id", pid).single().execute()
                        product_name = (pr.data or {}).get("name")
                    except Exception:
                        pass
                enriched_items.append({
                    "product_id": pid,
                    "product_name": product_name or pid,
                    "quantity": item.get("quantity"),
                    "unit_price": item.get("unit_price"),
                    "unit": item.get("unit"),
                })
            requests.append({
                "subscription_id": row["id"],
                "from_user_id": counterpart_id,
                "frequency": row.get("frequency", ""),
                "start_date": row.get("start_date", ""),
                "notes": row.get("notes", ""),
                "items": enriched_items,
            })
        return {"success": True, "requests": requests, "count": len(requests)}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ─────────────────────────────────────────────
# (7) TOOL_FUNCTION_MAP — registry + 잔존 4개 통합본
# ─────────────────────────────────────────────
# orchestrator 의 `from app.services.agent_tools import TOOL_FUNCTION_MAP` 호환.
# registry (33+4=37) + 이 파일에 남은 chat 3 + subscription 1 = 41.
# 옮긴 37 개는 registry 에서 자동으로 가져오고, 잔존 4 개만 직접 추가.

from app.services.agent import (
    TOOL_FUNCTION_MAP as _REGISTRY_MAP,
    TOOLS as _REGISTRY_TOOLS,
    TOOLS_CALENDAR as _REGISTRY_TOOLS_CALENDAR,
    TOOLS_CHAT as _REGISTRY_TOOLS_CHAT,
    INT_FIELDS as _REGISTRY_INT_FIELDS,
)

TOOL_FUNCTION_MAP: dict = {
    **_REGISTRY_MAP,  # 37개 — 도메인 모듈에서 @tool 등록 (33 inventory_order + 4 calendar)
    # chat 3 (PR 3 에서 chat 도메인 모듈로 이동)
    "get_chat_rooms": get_chat_rooms,
    "get_chat_messages": get_chat_messages,
    "send_chat_message": send_chat_message,
    # subscription 1 (PR 3 이후 subscription 도메인 모듈로 이동)
    "get_incoming_subscription_requests": get_incoming_subscription_requests,
}

# OpenAI tool calling schema 재노출 — 외부 호환용.
# 옮긴 37 개 스키마는 ToolRegistry 가 자동 노출 (inventory_order 33 + calendar 4).
# 잔존 chat 스키마는 orchestrator.py 에 그대로 남아있고, PR 3 에서 도메인 모듈로
# 이동 시 agent.TOOLS_CHAT 가 그 책임을 넘겨받는다.
#
# PR 2 시점 기대 값:
# - TOOLS:           33 (registry, "inventory_order" 그룹)
# - TOOLS_CALENDAR:  4  (PR 2 에서 채워짐 — registry "calendar" 그룹)
# - TOOLS_CHAT:      0  (PR 3 에서 채워짐 — 현재는 orchestrator.py 가 보유)
TOOLS = _REGISTRY_TOOLS
TOOLS_CALENDAR = _REGISTRY_TOOLS_CALENDAR
TOOLS_CHAT = _REGISTRY_TOOLS_CHAT
INT_FIELDS = _REGISTRY_INT_FIELDS
