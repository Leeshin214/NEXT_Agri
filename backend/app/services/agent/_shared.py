"""cross-domain 공통 헬퍼.

여러 도메인 도구가 공유하는 유틸 (UUID 검증, async runner, 공통 응답 빌더,
order/calendar/seller/product 검색·동기화 헬퍼) 의 단일 정의 위치.

도메인 특정 helper 는 해당 도메인 모듈 안에 둔다 (예: tools/product.py 의
`_find_product_by_name` — order/subscription 가 lazy import 로 재사용).

PR 4 (이 파일이 채워진 시점) 이전에는 `agent_tools.py` 가 이 helper 들을
보관하고 있었으나, shim 제거와 함께 모두 이쪽으로 이동했다. 도메인 모듈은
`from .._shared import _xxx` 로 module-level import 가능 (cross-domain 의존성
순서 이슈가 없음 — _shared 는 도메인 모듈을 import 하지 않음).
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Optional


# ─────────────────────────────────────────────
# UUID 검증
# ─────────────────────────────────────────────

_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)


# ─────────────────────────────────────────────
# async runner
# ─────────────────────────────────────────────

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
# calendar 동기화
# ─────────────────────────────────────────────

def _sync_calendar_events_for_order_id(order_id: str) -> None:
    from app.services.order_service import order_service

    order_service.sync_calendar_events_for_order_id(order_id)


# ─────────────────────────────────────────────
# 사용자 / 상품 lookup (cross-domain)
# ─────────────────────────────────────────────

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
    _find_product_by_name` 으로 가져간다. 이 모듈의 정의는 외부 코드 (chat_ws 등)
    가 cross-domain 형태로 호출할 때를 위한 호환용.
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


# ─────────────────────────────────────────────
# 판매자 재고 차감 (CONFIRMED 전이 시)
# ─────────────────────────────────────────────

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


__all__ = [
    "_UUID_PATTERN",
    "_run_async_in_thread",
    "_service_error_payload",
    "_sync_calendar_events_for_order_id",
    "_find_seller_by_name",
    "_find_product_by_name",
    "_deduct_seller_stock_for_order",
]
