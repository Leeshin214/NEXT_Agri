"""Deprecated re-export shim — 도구는 backend/app/services/agent/tools/ 로 이동.

이 파일은 chat_ws.py / orchestrator.py / 기타 외부 코드의 backward compat 을
유지하기 위해 남아있다. 옮긴 도구들은 `from app.services.agent.tools.<domain>` 에서
직접 import 해도 동일한 함수 객체를 가져올 수 있다 (re-export).

남는 책임:
1. 옮긴 40 개 도구 함수 + analyze_chat_consensus re-export (chat_ws.py / 외부 호출 호환).
2. 아직 도메인 모듈로 옮기지 않은 cross-domain helper 들의 단일 정의 위치.
   (`_UUID_PATTERN`, `_run_async_in_thread`, `_service_error_payload`,
    `_sync_calendar_events_for_order_id`, `_find_seller_by_name`,
    `_find_product_by_name`, `_deduct_seller_stock_for_order` 등)
3. 아직 옮기지 않은 1 개 도구 (subscription: get_incoming_subscription_requests) 의 본문.
4. `TOOL_FUNCTION_MAP` — registry + 잔존 1개 통합본 (orchestrator import 호환).

PR 3 에서 chat 도메인 모듈을 신설해 chat 3 + analyze_chat_consensus 를 모두 옮겼다.
PR 4 에서 이 파일과 cross-domain helper 를 `agent/_shared.py` 로 이동하고
shim 자체를 제거할 예정이다.
"""

import asyncio
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
from app.services.agent.tools.chat import (  # noqa: F401
    get_chat_rooms,
    get_chat_messages,
    send_chat_message,
    analyze_chat_consensus,  # 헬퍼 (LLM 도구 미등록 — chat_ws.py 호환)
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
# (3) 채팅 도구 — PR 3 에서 agent.tools.chat 로 이동 완료
# ─────────────────────────────────────────────
# 3 개 함수 (get_chat_rooms / get_chat_messages / send_chat_message) 의 본문은
# `app.services.agent.tools.chat` 모듈로 이동했다. 이 파일 상단의
# `from ...chat import ...` re-export 로 backward compat 유지.
# ToolRegistry 가 자동으로 TOOL_FUNCTION_MAP / TOOLS_CHAT 에 노출.
# `analyze_chat_consensus` 도 chat 모듈에 정의되어 있고 (LLM 도구 미등록),
# 이 파일 상단에서 함께 re-export 된다 (chat_ws.py 직접 호출 호환).


# ─────────────────────────────────────────────
# (4) 캘린더 도구 — PR 2 에서 agent.tools.calendar 로 이동 완료
# ─────────────────────────────────────────────
# 4 개 함수 (get/create/update/delete_calendar_event) 의 본문은
# `app.services.agent.tools.calendar` 모듈로 이동했다. 이 파일 상단의
# `from ...calendar import ...` re-export 로 backward compat 유지.
# ToolRegistry 가 자동으로 TOOL_FUNCTION_MAP / TOOLS_CALENDAR 에 노출.


# ─────────────────────────────────────────────
# (5) 정기배송 — 들어온 PENDING 요청 조회 (도메인 모듈 미이동)
# ─────────────────────────────────────────────
# create/accept/reject_subscription_request 와 create_subscription_from_order
# 는 agent.tools.subscription 으로 이동했지만,
# get_incoming_subscription_requests 는 아직 도메인 모듈로 옮기지 않았다 (다음 PR).

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
# (6) TOOL_FUNCTION_MAP — registry + 잔존 1개 통합본
# ─────────────────────────────────────────────
# orchestrator 의 `from app.services.agent_tools import TOOL_FUNCTION_MAP` 호환.
# registry (33 inventory_order + 4 calendar + 3 chat = 40) + 이 파일에 남은
# subscription 1 (get_incoming_subscription_requests) = 41.
# 옮긴 40 개는 registry 에서 자동으로 가져오고, 잔존 1 개만 직접 추가.
# analyze_chat_consensus 는 LLM 도구가 아니므로 등록하지 않는다 (chat_ws 가 직접 호출).

from app.services.agent import (
    TOOL_FUNCTION_MAP as _REGISTRY_MAP,
    TOOLS as _REGISTRY_TOOLS,
    TOOLS_CALENDAR as _REGISTRY_TOOLS_CALENDAR,
    TOOLS_CHAT as _REGISTRY_TOOLS_CHAT,
    INT_FIELDS as _REGISTRY_INT_FIELDS,
)

TOOL_FUNCTION_MAP: dict = {
    **_REGISTRY_MAP,  # 40개 — 도메인 모듈에서 @tool 등록 (33 inventory_order + 4 calendar + 3 chat)
    # subscription 1 (다음 PR 에서 subscription 도메인 모듈로 이동)
    "get_incoming_subscription_requests": get_incoming_subscription_requests,
}

# OpenAI tool calling schema 재노출 — 외부 호환용.
# 옮긴 40 개 스키마는 ToolRegistry 가 자동 노출 (inventory_order 33 + calendar 4 + chat 3).
#
# PR 3 시점 기대 값:
# - TOOLS:           33 (registry, "inventory_order" 그룹)
# - TOOLS_CALENDAR:  4  (PR 2, "calendar" 그룹)
# - TOOLS_CHAT:      3  (PR 3, "chat" 그룹)
TOOLS = _REGISTRY_TOOLS
TOOLS_CALENDAR = _REGISTRY_TOOLS_CALENDAR
TOOLS_CHAT = _REGISTRY_TOOLS_CHAT
INT_FIELDS = _REGISTRY_INT_FIELDS
