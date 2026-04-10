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
# 헬퍼: 이름 기반 상품 검색 (fuzzy fallback 포함)
# ─────────────────────────────────────────────

def _find_product_by_name(supabase, product_name: str, seller_id: str = "") -> Optional[dict]:
    """
    product_name으로 상품을 검색한다.
    1차: 전체 문자열 ilike 검색
    2차: 실패 시 각 글자를 한 개씩 포함하는 검색으로 fallback (LLM 철자 오류 대응)
    반환: {"id": ..., "name": ...} 또는 None
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


def check_stock(product_id: str, seller_id: str = "", product_name: Optional[str] = None) -> dict:
    """특정 상품의 재고 현황을 상세 조회한다. product_id가 없으면 seller_id + product_name으로 검색."""
    try:
        supabase = get_supabase_client()

        if not product_id or len(product_id) < 10:
            if not product_name:
                return {"success": False, "error": "상품 ID 또는 상품명을 알려주세요.", "product": None}
            found = _find_product_by_name(supabase, product_name, seller_id)
            if not found:
                return {"success": False, "error": f"'{product_name}' 상품을 찾을 수 없습니다.", "product": None}
            # 상세 정보 추가 조회
            detail = (
                supabase.table("products")
                .select("id, name, category, stock_quantity, unit, status, min_order_qty, price_per_unit")
                .eq("id", found["id"])
                .execute()
            )
            return {"success": True, "product": detail.data[0] if detail.data else found}

        result = (
            supabase.table("products")
            .select("id, name, category, stock_quantity, unit, status, min_order_qty, price_per_unit")
            .eq("id", product_id)
            .execute()
        )

        if not result.data:
            return {"success": False, "error": "해당 상품을 찾을 수 없습니다.", "product": None}

        return {"success": True, "product": result.data[0]}
    except Exception as e:
        return {"success": False, "error": str(e), "product": None}


def update_stock(product_id: str = "", new_quantity: int = 0, seller_id: str = "", product_name: Optional[str] = None) -> dict:
    """특정 상품의 재고 수량을 업데이트한다. 수량에 따라 status도 자동 변경. product_id가 없으면 seller_id + product_name으로 검색."""
    try:
        supabase = get_supabase_client()

        # product_id가 없으면 이름으로 검색
        if not product_id or len(product_id) < 10:
            if not product_name:
                return {"success": False, "error": "상품 ID 또는 상품명을 알려주세요."}
            found = _find_product_by_name(supabase, product_name, seller_id)
            if not found:
                return {"success": False, "error": f"'{product_name}' 상품을 찾을 수 없습니다."}
            product_id = found["id"]
            resolved_name = found["name"]
        else:
            resolved_name = ""

        # 재고 수량에 따라 상태 자동 결정
        # 0이면 품절, 10 미만이면 부족, 그 이상이면 정상
        if new_quantity == 0:
            new_status = "OUT_OF_STOCK"
        elif new_quantity < 10:
            new_status = "LOW_STOCK"
        else:
            new_status = "NORMAL"

        supabase.table("products").update({"stock_quantity": new_quantity, "status": new_status}).eq("id", product_id).execute()

        return {
            "success": True,
            "product_id": product_id,
            "new_quantity": new_quantity,
            "new_status": new_status,
            "product_name": resolved_name,
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
    # 필수값 검증
    if not name or not category or price_per_unit is None or stock_quantity is None or not unit:
        return {"success": False, "error": "필수 정보가 부족합니다. 상품명, 카테고리, 단가, 재고 수량, 단위를 모두 입력해주세요."}
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

            supabase.table("products").update({"stock_quantity": new_qty, "status": new_status}).eq("id", existing_product["id"]).execute()

            return {
                "success": True,
                "product": existing_product,
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

        return {
            "success": True,
            "product": result.data[0] if result.data else {"name": name, "category": category},
            "message": f"{name} 상품이 등록되었습니다.",
            "action": "created",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def delete_product(product_id: str, seller_id: str, name: Optional[str] = None) -> dict:
    """상품을 삭제한다. product_id 또는 name으로 찾아서 soft delete."""
    try:
        supabase = get_supabase_client()

        # product_id가 없거나 비어있으면 이름으로 검색
        if not product_id or len(product_id) < 10:
            if not name:
                return {"success": False, "error": "삭제할 상품명을 알려주세요."}
            check = (
                supabase.table("products")
                .select("id, name, seller_id")
                .eq("seller_id", seller_id)
                .ilike("name", f"%{name}%")
                .is_("deleted_at", None)
                .execute()
            )
            if not check.data:
                return {"success": False, "error": f"'{name}' 상품을 찾을 수 없습니다."}
            if len(check.data) > 1:
                names = ", ".join([p["name"] for p in check.data])
                return {"success": False, "error": f"'{name}'과 일치하는 상품이 여러 개입니다: {names}. 더 정확한 이름을 알려주세요."}
            product_id = check.data[0]["id"]
            product_name = check.data[0]["name"]
        else:
            check = (
                supabase.table("products")
                .select("id, name, seller_id")
                .eq("id", product_id)
                .is_("deleted_at", None)
                .execute()
            )
            if not check.data:
                return {"success": False, "error": "해당 상품을 찾을 수 없습니다."}
            if check.data[0]["seller_id"] != seller_id:
                return {"success": False, "error": "권한 없음: 본인 상품만 삭제할 수 있습니다."}
            product_name = check.data[0]["name"]

        now_utc = datetime.now(timezone.utc).isoformat()
        supabase.table("products").update({"deleted_at": now_utc}).eq("id", product_id).execute()

        # 실제로 삭제됐는지 검증
        verify = supabase.table("products").select("id, deleted_at").eq("id", product_id).execute()
        if not verify.data or verify.data[0].get("deleted_at") is None:
            return {"success": False, "error": "상품 삭제에 실패했습니다."}

        return {
            "success": True,
            "product_id": product_id,
            "product_name": product_name,
            "message": f"{product_name} 상품이 삭제되었습니다.",
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
    product_name: Optional[str] = None,
) -> dict:
    """상품 정보를 수정한다. product_id 또는 product_name으로 상품을 찾아 수정한다."""
    try:
        supabase = get_supabase_client()

        # product_id가 없으면 이름으로 검색
        if not product_id or len(product_id) < 10:
            search_name = product_name or name
            if not search_name:
                return {"success": False, "error": "수정할 상품명을 알려주세요."}
            check = (
                supabase.table("products")
                .select("id, name, seller_id")
                .eq("seller_id", seller_id)
                .ilike("name", f"%{search_name}%")
                .is_("deleted_at", None)
                .execute()
            )
            if not check.data:
                return {"success": False, "error": f"'{search_name}' 상품을 찾을 수 없습니다."}
            product_id = check.data[0]["id"]
        else:
            check = (
                supabase.table("products")
                .select("id, name, seller_id")
                .eq("id", product_id)
                .is_("deleted_at", None)
                .execute()
            )
            if not check.data:
                return {"success": False, "error": "해당 상품을 찾을 수 없습니다."}
            if check.data[0]["seller_id"] != seller_id:
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

        supabase.table("products").update(update_data).eq("id", product_id).execute()

        return {
            "success": True,
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
        order_data = order_result.data[0]
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

        supabase.table("orders").update({"status": new_status}).eq("id", order_id).execute()

        return {
            "success": True,
            "order_id": order_id,
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
            .execute()
        )

        if not check.data:
            return {"success": False, "error": "해당 주문을 찾을 수 없습니다."}

        order_data = check.data[0]
        if order_data["buyer_id"] != user_id and order_data["seller_id"] != user_id:
            return {"success": False, "error": "권한 없음: 해당 주문에 접근할 수 없습니다."}

        now_utc = datetime.now(timezone.utc).isoformat()
        supabase.table("orders").update({"deleted_at": now_utc}).eq("id", order_id).execute()

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

def find_sellers_by_product(category: str, product_name: Optional[str] = None) -> dict:
    """특정 카테고리를 판매 중인 판매자 목록을 넓게 조회한다. 세부 필터링은 LLM이 담당."""
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

        # 상품명으로 추가 필터링
        if product_name:
            query = query.ilike("name", f"%{product_name}%")
            
        # 재고가 있고 삭제되지 않은 상품만 조회
        result = (
            query
            .gt("stock_quantity", 0)
            .is_("deleted_at", None)
            .execute()
        )

        products = result.data or []

        # seller_id 목록으로 users 테이블 조회
        seller_ids = list({p["seller_id"] for p in products if p.get("seller_id")})
        seller_map = {}
        if seller_ids:
            users_result = (
                supabase.table("users")
                .select("id, name, company_name, phone")
                .in_("id", seller_ids)
                .execute()
            )
            for u in (users_result.data or []):
                seller_map[u["id"]] = u

        # 상품 데이터에 판매자 정보 합치기
        enriched = []
        for p in products:
            seller_info = seller_map.get(p.get("seller_id"), {})
            enriched.append({
                **p,
                "seller_name": seller_info.get("name", "알 수 없음"),
                "seller_company": seller_info.get("company_name", ""),
                "seller_phone": seller_info.get("phone", ""),
            })

        return {
            "success": True,
            "sellers": enriched,
            "count": len(enriched),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "sellers": [], "count": 0}


def find_buyers_by_product(category: str) -> dict:
    """특정 카테고리 상품을 구매한 바이어 목록을 넓게 조회한다. 세부 필터링은 LLM이 담당."""
    try:
        supabase = get_supabase_client()

        # products 테이블에서 해당 카테고리 상품 ID 먼저 조회
        prod_query = supabase.table("products").select("id, name, category")
        if category and category.upper() != "ALL":
            prod_query = prod_query.eq("category", category.upper())
        prod_result = prod_query.execute()

        if not prod_result.data:
            return {"success": True, "buyers": [], "count": 0}

        product_ids = [p["id"] for p in prod_result.data]

        # 해당 상품들의 order_items 조회
        items_result = (
            supabase.table("order_items")
            .select("order_id, quantity, product_id, orders!inner(buyer_id, status)")
            .in_("product_id", product_ids)
            .execute()
        )

        # buyer_id별로 집계
        buyer_stats: dict = {}
        for item in items_result.data or []:
            buyer_id = item["orders"]["buyer_id"]
            if buyer_id not in buyer_stats:
                buyer_stats[buyer_id] = {"buyer_id": buyer_id, "order_count": 0, "total_quantity": 0}
            buyer_stats[buyer_id]["order_count"] += 1
            buyer_stats[buyer_id]["total_quantity"] += item["quantity"]

        buyers = sorted(buyer_stats.values(), key=lambda x: x["total_quantity"], reverse=True)

        return {"success": True, "buyers": buyers, "count": len(buyers)}
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
