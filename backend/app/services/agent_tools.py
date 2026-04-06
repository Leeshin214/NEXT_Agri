"""
agent_tools.py — LangGraph 오케스트레이터에서 실제로 호출되는 도구 함수들

각 함수는 Supabase DB를 직접 조회/수정하고, 결과를 dict로 반환한다.
오케스트레이터(orchestrator.py)가 LLM의 tool 선택에 따라 TOOL_FUNCTION_MAP을 통해 실행한다.
현재 LLM: Groq (meta-llama/llama-4-scout) — Claude API 확보 시 orchestrator.py만 수정하면 됨.
"""

import asyncio
from typing import Optional

from app.core.supabase import get_supabase_client


# ─────────────────────────────────────────────
# 상품 / 재고 관련 도구
# ─────────────────────────────────────────────

def get_products(seller_id: str, category: Optional[str] = None) -> dict:
    """판매자의 상품 목록을 조회한다. category를 주면 해당 카테고리만 필터링."""
    try:
        supabase = get_supabase_client()

        # 기본 쿼리: 판매자 ID로 필터, 삭제된 상품 제외
        query = (
            supabase.table("products")
            .select("*")
            .eq("seller_id", seller_id)
            .is_("deleted_at", "null")
        )

        # 카테고리가 지정된 경우 추가 필터
        if category:
            query = query.eq("category", category)

        result = query.order("name").execute()

        return {
            "success": True,
            "products": result.data or [],
            "count": len(result.data or []),
        }
    except Exception as e:
        # 오류 발생 시 실패 정보를 Claude에게 전달 (함수 자체는 터뜨리지 않음)
        return {"success": False, "error": str(e), "products": [], "count": 0}


def check_stock(product_id: str) -> dict:
    """특정 상품의 재고 현황을 상세 조회한다."""
    try:
        supabase = get_supabase_client()

        result = (
            supabase.table("products")
            .select("id, name, category, stock_quantity, unit, status, min_order, price_per_unit")
            .eq("id", product_id)
            .single()
            .execute()
        )

        if not result.data:
            return {"success": False, "error": "해당 상품을 찾을 수 없습니다.", "product": None}

        return {"success": True, "product": result.data}
    except Exception as e:
        return {"success": False, "error": str(e), "product": None}


def update_stock(product_id: str, new_quantity: int) -> dict:
    """특정 상품의 재고 수량을 업데이트한다. 수량에 따라 status도 자동 변경."""
    try:
        supabase = get_supabase_client()

        # 재고 수량에 따라 상태 자동 결정
        # 0이면 품절, 10 미만이면 부족, 그 이상이면 정상
        if new_quantity == 0:
            new_status = "OUT_OF_STOCK"
        elif new_quantity < 10:
            new_status = "LOW_STOCK"
        else:
            new_status = "NORMAL"

        result = (
            supabase.table("products")
            .update({"stock_quantity": new_quantity, "status": new_status})
            .eq("id", product_id)
            .execute()
        )

        if not result.data:
            return {"success": False, "error": "상품을 찾을 수 없거나 업데이트에 실패했습니다."}

        updated = result.data[0]
        return {
            "success": True,
            "product_id": product_id,
            "new_quantity": new_quantity,
            "new_status": new_status,
            "product_name": updated.get("name", ""),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ─────────────────────────────────────────────
# 주문 관련 도구
# ─────────────────────────────────────────────

def get_orders(user_id: str, role: str, status: Optional[str] = None) -> dict:
    """사용자의 주문 목록을 조회한다. role에 따라 buyer_id / seller_id로 필터링."""
    try:
        supabase = get_supabase_client()

        # 역할에 따라 어느 컬럼으로 필터할지 결정
        # 판매자는 자신이 받은 주문(seller_id), 구매자는 자신이 넣은 주문(buyer_id)
        if role == "SELLER":
            id_column = "seller_id"
        else:
            id_column = "buyer_id"

        query = (
            supabase.table("orders")
            .select(
                "id, order_number, status, total_amount, delivery_date, "
                "delivery_address, notes, created_at, buyer_id, seller_id"
            )
            .eq(id_column, user_id)
        )

        # 특정 상태로 필터링 (예: QUOTE_REQUESTED, SHIPPING 등)
        if status:
            query = query.eq("status", status)

        result = query.order("created_at", desc=True).limit(20).execute()

        return {
            "success": True,
            "orders": result.data or [],
            "count": len(result.data or []),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "orders": [], "count": 0}


def get_order_detail(order_id: str) -> dict:
    """주문 상세 정보와 주문 항목(order_items)을 함께 조회한다."""
    try:
        supabase = get_supabase_client()

        # 주문 기본 정보 조회
        order_result = (
            supabase.table("orders")
            .select(
                "id, order_number, status, total_amount, delivery_date, "
                "delivery_address, notes, created_at, buyer_id, seller_id"
            )
            .eq("id", order_id)
            .single()
            .execute()
        )

        if not order_result.data:
            return {"success": False, "error": "해당 주문을 찾을 수 없습니다.", "order": None}

        # 주문 항목 조회 (어떤 상품이 몇 개, 단가가 얼마인지)
        items_result = (
            supabase.table("order_items")
            .select("id, product_id, quantity, unit_price, subtotal")
            .eq("order_id", order_id)
            .execute()
        )

        # 주문 정보에 항목 리스트를 합쳐서 반환
        order_data = order_result.data
        order_data["items"] = items_result.data or []
        order_data["items_count"] = len(items_result.data or [])

        return {"success": True, "order": order_data}
    except Exception as e:
        return {"success": False, "error": str(e), "order": None}


def update_order_status(order_id: str, new_status: str) -> dict:
    """주문의 상태를 변경한다. 유효한 상태값인지 먼저 검증한다."""
    # 허용된 주문 상태 목록 (도메인 규칙)
    VALID_STATUSES = [
        "QUOTE_REQUESTED",
        "NEGOTIATING",
        "CONFIRMED",
        "PREPARING",
        "SHIPPING",
        "COMPLETED",
        "CANCELLED",
    ]

    try:
        # 유효하지 않은 상태값이 들어오면 오류 반환
        if new_status not in VALID_STATUSES:
            return {
                "success": False,
                "error": f"유효하지 않은 상태입니다. 허용 상태: {', '.join(VALID_STATUSES)}",
            }

        supabase = get_supabase_client()

        result = (
            supabase.table("orders")
            .update({"status": new_status})
            .eq("id", order_id)
            .execute()
        )

        if not result.data:
            return {"success": False, "error": "주문을 찾을 수 없거나 업데이트에 실패했습니다."}

        updated = result.data[0]
        return {
            "success": True,
            "order_id": order_id,
            "order_number": updated.get("order_number", ""),
            "new_status": new_status,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ─────────────────────────────────────────────
# tool 이름 → 함수 매핑 테이블
# ─────────────────────────────────────────────

# 오케스트레이터가 Claude의 tool_use 응답에서 tool 이름을 보고
# 실제 어떤 함수를 실행할지 찾을 때 이 딕셔너리를 사용한다.
TOOL_FUNCTION_MAP = {
    "get_products": get_products,
    "check_stock": check_stock,
    "update_stock": update_stock,
    "get_orders": get_orders,
    "get_order_detail": get_order_detail,
    "update_order_status": update_order_status,
}
