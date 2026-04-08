"""
agent_tools.py — LangGraph 오케스트레이터에서 실제로 호출되는 도구 함수들

각 함수는 Supabase DB를 직접 조회/수정하고, 결과를 dict로 반환한다.
오케스트레이터(orchestrator.py)가 LLM의 tool 선택에 따라 TOOL_FUNCTION_MAP을 통해 실행한다.
현재 LLM: Groq (meta-llama/llama-4-scout) — Claude API 확보 시 orchestrator.py만 수정하면 됨.
"""

import asyncio
import random
from datetime import datetime, timezone
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
            .is_("deleted_at", None)
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


def create_product(
    seller_id: str,
    name: str,
    category: str,
    price_per_unit: int,
    stock_quantity: int,
    unit: str,
    origin: Optional[str] = None,
    spec: Optional[str] = None,
    min_order_qty: Optional[int] = None,
    description: Optional[str] = None,
) -> dict:
    """새 상품을 등록한다. 같은 판매자 + 같은 상품명이 이미 존재하면 재고를 합산한다."""
    try:
        supabase = get_supabase_client()

        # 같은 판매자 + 같은 상품명 있는지 먼저 확인
        existing = (
            supabase.table("products")
            .select("id, stock_quantity, name")
            .eq("seller_id", seller_id)
            .eq("name", name)
            .is_("deleted_at", None)
            .execute()
        )

        if existing.data:
            # 이미 있으면 재고 합산
            existing_product = existing.data[0]
            new_qty = existing_product["stock_quantity"] + stock_quantity

            # 상태 재계산
            if new_qty == 0:
                new_status = "OUT_OF_STOCK"
            elif new_qty < 10:
                new_status = "LOW_STOCK"
            else:
                new_status = "NORMAL"

            result = (
                supabase.table("products")
                .update({"stock_quantity": new_qty, "status": new_status})
                .eq("id", existing_product["id"])
                .execute()
            )

            return {
                "success": True,
                "product": result.data[0] if result.data else existing_product,
                "message": f"{name} 상품이 이미 존재하여 재고를 {stock_quantity} 추가했습니다. 현재 재고: {new_qty}",
                "action": "stock_merged",
            }

        # 없으면 새로 등록
        # 재고에 따라 초기 상태 결정
        if stock_quantity == 0:
            status = "OUT_OF_STOCK"
        elif stock_quantity < 10:
            status = "LOW_STOCK"
        else:
            status = "NORMAL"

        result = (
            supabase.table("products")
            .insert({
                "seller_id": seller_id,
                "name": name,
                "category": category,
                "price_per_unit": price_per_unit,
                "stock_quantity": stock_quantity,
                "unit": unit,
                "origin": origin,
                "spec": spec,
                "min_order_qty": min_order_qty,
                "description": description,
                "status": status,
            })
            .execute()
        )

        if not result.data:
            return {"success": False, "error": "상품 등록에 실패했습니다."}

        return {
            "success": True,
            "product": result.data[0],
            "message": f"{name} 상품이 등록되었습니다.",
            "action": "created",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def delete_product(product_id: str, seller_id: str) -> dict:
    """상품을 삭제한다. 실제 삭제가 아닌 deleted_at을 현재 시간으로 설정한다."""
    try:
        supabase = get_supabase_client()

        # seller_id 일치 확인
        check = (
            supabase.table("products")
            .select("id, name, seller_id")
            .eq("id", product_id)
            .is_("deleted_at", None)
            .single()
            .execute()
        )

        if not check.data:
            return {"success": False, "error": "해당 상품을 찾을 수 없습니다."}

        if check.data["seller_id"] != seller_id:
            return {"success": False, "error": "권한 없음: 본인 상품만 삭제할 수 있습니다."}

        now_utc = datetime.now(timezone.utc).isoformat()
        result = (
            supabase.table("products")
            .update({"deleted_at": now_utc})
            .eq("id", product_id)
            .execute()
        )

        if not result.data:
            return {"success": False, "error": "상품 삭제에 실패했습니다."}

        return {
            "success": True,
            "product_id": product_id,
            "product_name": check.data.get("name", ""),
            "message": f"{check.data.get('name', '')} 상품이 삭제되었습니다.",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def update_product(
    product_id: str,
    seller_id: str,
    name: Optional[str] = None,
    price_per_unit: Optional[int] = None,
    category: Optional[str] = None,
    origin: Optional[str] = None,
    spec: Optional[str] = None,
    description: Optional[str] = None,
) -> dict:
    """상품 정보를 수정한다. 전달된 필드만 업데이트한다."""
    try:
        supabase = get_supabase_client()

        # seller_id 권한 확인
        check = (
            supabase.table("products")
            .select("id, name, seller_id")
            .eq("id", product_id)
            .is_("deleted_at", None)
            .single()
            .execute()
        )

        if not check.data:
            return {"success": False, "error": "해당 상품을 찾을 수 없습니다."}

        if check.data["seller_id"] != seller_id:
            return {"success": False, "error": "권한 없음: 본인 상품만 수정할 수 있습니다."}

        # None이 아닌 필드만 update dict에 포함
        update_data: dict = {}
        if name is not None:
            update_data["name"] = name
        if price_per_unit is not None:
            update_data["price_per_unit"] = price_per_unit
        if category is not None:
            update_data["category"] = category
        if origin is not None:
            update_data["origin"] = origin
        if spec is not None:
            update_data["spec"] = spec
        if description is not None:
            update_data["description"] = description

        if not update_data:
            return {"success": False, "error": "수정할 필드가 없습니다."}

        result = (
            supabase.table("products")
            .update(update_data)
            .eq("id", product_id)
            .execute()
        )

        if not result.data:
            return {"success": False, "error": "상품 수정에 실패했습니다."}

        return {
            "success": True,
            "product": result.data[0],
            "message": f"상품 정보가 업데이트되었습니다.",
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


def create_order(
    buyer_id: str,
    seller_id: str,
    product_id: str,
    quantity: int,
    unit_price: int,
    delivery_date: Optional[str] = None,
    delivery_address: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    """새 주문을 생성한다."""
    try:
        supabase = get_supabase_client()

        # order_number: ORD-{YYYYMMDD}-{랜덤4자리}
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        rand_suffix = str(random.randint(1000, 9999))
        order_number = f"ORD-{today}-{rand_suffix}"

        subtotal = quantity * unit_price
        total_amount = subtotal

        # orders 테이블에 INSERT
        order_result = (
            supabase.table("orders")
            .insert({
                "order_number": order_number,
                "buyer_id": buyer_id,
                "seller_id": seller_id,
                "status": "QUOTE_REQUESTED",
                "total_amount": total_amount,
                "delivery_date": delivery_date,
                "delivery_address": delivery_address,
                "notes": notes,
            })
            .execute()
        )

        if not order_result.data:
            return {"success": False, "error": "주문 생성에 실패했습니다."}

        order = order_result.data[0]
        order_id = order["id"]

        # order_items 테이블에 INSERT
        items_result = (
            supabase.table("order_items")
            .insert({
                "order_id": order_id,
                "product_id": product_id,
                "quantity": quantity,
                "unit_price": unit_price,
                "subtotal": subtotal,
            })
            .execute()
        )

        return {
            "success": True,
            "order": order,
            "order_items": items_result.data or [],
            "message": f"주문 {order_number}이 생성되었습니다.",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def delete_order(order_id: str, user_id: str) -> dict:
    """주문을 삭제한다. buyer_id 또는 seller_id가 일치하는 경우만 가능."""
    try:
        supabase = get_supabase_client()

        # 주문 존재 및 권한 확인
        check = (
            supabase.table("orders")
            .select("id, order_number, buyer_id, seller_id")
            .eq("id", order_id)
            .is_("deleted_at", None)
            .single()
            .execute()
        )

        if not check.data:
            return {"success": False, "error": "해당 주문을 찾을 수 없습니다."}

        order_data = check.data
        if order_data["buyer_id"] != user_id and order_data["seller_id"] != user_id:
            return {"success": False, "error": "권한 없음: 해당 주문에 접근할 수 없습니다."}

        now_utc = datetime.now(timezone.utc).isoformat()
        result = (
            supabase.table("orders")
            .update({"deleted_at": now_utc})
            .eq("id", order_id)
            .execute()
        )

        if not result.data:
            return {"success": False, "error": "주문 삭제에 실패했습니다."}

        return {
            "success": True,
            "order_id": order_id,
            "order_number": order_data.get("order_number", ""),
            "message": f"주문 {order_data.get('order_number', '')}이 삭제되었습니다.",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ─────────────────────────────────────────────
# 거래처 찾기 도구
# ─────────────────────────────────────────────

def find_sellers_by_product(category: str) -> dict:
    """특정 카테고리를 판매 중인 판매자 목록을 넓게 조회한다. 세부 필터링은 LLM이 담당."""
    import logging
    logger = logging.getLogger(__name__)
    try:
        supabase = get_supabase_client()

        # 기본 쿼리 세팅 (카테고리 정보도 같이 가져옴)
        query = (
            supabase.table("products")
            .select("seller_id, name, price_per_unit, stock_quantity, unit, origin, spec, status, category")
        )

        # 'ALL'이 아니면 해당 카테고리로만 필터링
        if category and category.upper() != "ALL":
            query = query.eq("category", category.upper())
            
        # 재고가 있고 삭제되지 않은 상품만 조회
        result = (
            query
            .gt("stock_quantity", 0)
            .is_("deleted_at", None)
            .execute()
        )
        
        logger.warning(f"[DEBUG] 스마트 필터링 용 데이터 로드 완료: {len(result.data or [])}건")
        
        return {
            "success": True,
            "sellers": result.data or [],
            "count": len(result.data or []),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "sellers": [], "count": 0}


def find_buyers_by_product(category: str) -> dict:
    """특정 카테고리 상품을 구매한 바이어 목록을 넓게 조회한다. 세부 필터링은 LLM이 담당."""
    try:
        supabase = get_supabase_client()
        
        # 기본 쿼리 세팅 (products 테이블과 조인하여 카테고리 정보 확인)
        query = (
            supabase.table("order_items")
            .select("order_id, quantity, orders!inner(buyer_id, status), products!inner(name, category)")
        )

        # 'ALL'이 아니면 해당 카테고리로만 필터링
        if category and category.upper() != "ALL":
            query = query.eq("products.category", category.upper())
            
        result = query.execute()

        # buyer_id별로 집계
        buyer_stats: dict = {}
        for item in result.data or []:
            buyer_id = item["orders"]["buyer_id"]
            if buyer_id not in buyer_stats:
                buyer_stats[buyer_id] = {"buyer_id": buyer_id, "order_count": 0, "total_quantity": 0}
            buyer_stats[buyer_id]["order_count"] += 1
            buyer_stats[buyer_id]["total_quantity"] += item["quantity"]

        buyers = sorted(buyer_stats.values(), key=lambda x: x["total_quantity"], reverse=True)

        return {
            "success": True,
            "buyers": buyers,
            "count": len(buyers),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "buyers": [], "count": 0}

# ─────────────────────────────────────────────
# tool 이름 → 함수 매핑 테이블
# ─────────────────────────────────────────────

# 오케스트레이터가 Claude의 tool_use 응답에서 tool 이름을 보고
# 실제 어떤 함수를 실행할지 찾을 때 이 딕셔너리를 사용한다.
TOOL_FUNCTION_MAP = {
    "get_products": get_products,
    "check_stock": check_stock,
    "update_stock": update_stock,
    "create_product": create_product,
    "delete_product": delete_product,
    "update_product": update_product,
    "get_orders": get_orders,
    "get_order_detail": get_order_detail,
    "update_order_status": update_order_status,
    "create_order": create_order,
    "delete_order": delete_order,
    "find_sellers_by_product": find_sellers_by_product,
    "find_buyers_by_product": find_buyers_by_product,
}
