"""
agent_tools.py — LangGraph 오케스트레이터에서 실제로 호출되는 도구 함수들

각 함수는 Supabase DB를 직접 조회/수정하고, 결과를 dict로 반환한다.
오케스트레이터(orchestrator.py)가 LLM의 tool 선택에 따라 TOOL_FUNCTION_MAP을 통해 실행한다.
현재 LLM: OpenAI (gpt-4o-mini)
"""

import asyncio
import json
import re
from calendar import monthrange
from datetime import datetime, timezone
from typing import Optional

from app.core.supabase import get_supabase_client


_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)


def _sync_calendar_events_for_order_id(order_id: str) -> None:
    from app.services.order_service import order_service

    order_service.sync_calendar_events_for_order_id(order_id)


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
        # 오류 발생 시 실패 정보를 LLM 에 전달 (함수 자체는 터뜨리지 않음)
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
    """사용자의 주문 목록을 조회한다. role에 따라 buyer_id / seller_id로 필터링.

    응답 평탄화 (LLM 토큰 절약 + 응답 우선순위 정책 — 상품명·거래처명 메인):
    - buyer_name / buyer_company / seller_name / seller_company
    - product_summary: "{첫 상품명}" 또는 "{첫 상품명} 외 N건" (items 비면 None)
    - items_count: order_items 길이
    임베딩 객체(buyer/seller/order_items)는 응답에서 제거.
    """
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
                "delivery_address, notes, created_at, buyer_id, seller_id, "
                "buyer:users!buyer_id(name,company_name), "
                "seller:users!seller_id(name,company_name), "
                "order_items(quantity, unit_price, products(name))"
            )
            .eq(id_column, user_id)
        )

        # 특정 상태로 필터링 (예: QUOTE_REQUESTED, SHIPPING 등)
        if status:
            query = query.eq("status", status)

        result = query.order("created_at", desc=True).limit(20).execute()

        rows = result.data or []
        flattened: list[dict] = []
        for row in rows:
            buyer = row.pop("buyer", None) or {}
            seller = row.pop("seller", None) or {}
            items = row.pop("order_items", None) or []

            row["buyer_name"] = buyer.get("name")
            row["buyer_company"] = buyer.get("company_name")
            row["seller_name"] = seller.get("name")
            row["seller_company"] = seller.get("company_name")

            product_names: list[str] = []
            item_summaries: list[str] = []

            row["primary_product_name"] = None
            row["primary_quantity"] = None
            row["primary_unit_price"] = None
            row["primary_subtotal"] = None

            for idx, item in enumerate(items):
                product = item.get("products") if isinstance(item, dict) else None
                if not product:
                    continue

                name = product.get("name")
                quantity = item.get("quantity")
                unit_price = item.get("unit_price")

                if name:
                    product_names.append(name)

                    if quantity is not None and unit_price is not None:
                        item_summaries.append(f"{name} {quantity}kg x {unit_price:,}원")
                    elif quantity is not None:
                        item_summaries.append(f"{name} {quantity}kg")
                    else:
                        item_summaries.append(name)

                if idx == 0:
                    row["primary_product_name"] = name
                    row["primary_quantity"] = quantity
                    row["primary_unit_price"] = unit_price
                    row["primary_subtotal"] = (
                        quantity * unit_price
                        if quantity is not None and unit_price is not None
                        else None
                    )

            if not product_names:
                row["product_summary"] = None
            elif len(product_names) == 1:
                row["product_summary"] = product_names[0]
            else:
                row["product_summary"] = f"{product_names[0]} 외 {len(product_names) - 1}건"

            row["item_summary"] = ", ".join(item_summaries) if item_summaries else None
            row["items_count"] = len(items)
            flattened.append(row)

        return {
            "success": True,
            "orders": flattened,
            "count": len(flattened),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "orders": [], "count": 0}


def get_order_detail(order_id: str) -> dict:
    """주문 상세 정보와 주문 항목(order_items)을 함께 조회한다.

    응답 평탄화 (응답 우선순위 정책 — 상품명·거래처명 메인):
    - order: buyer_name/buyer_company/seller_name/seller_company 추가
    - items[i]: product_name, product_unit 평탄화
    """
    try:
        supabase = get_supabase_client()

        # 주문 기본 정보 + buyer/seller 임베딩
        order_result = (
            supabase.table("orders")
            .select(
                "id, order_number, status, total_amount, delivery_date, "
                "delivery_address, notes, created_at, buyer_id, seller_id, "
                "buyer:users!buyer_id(name,company_name), "
                "seller:users!seller_id(name,company_name)"
            )
            .eq("id", order_id)
            .execute()
        )

        if not order_result.data:
            return {"success": False, "error": "해당 주문을 찾을 수 없습니다.", "order": None}

        # 주문 항목 조회 + products(name, unit) 임베딩
        items_result = (
            supabase.table("order_items")
            .select(
                "id, product_id, quantity, unit_price, subtotal, "
                "products(name, unit)"
            )
            .eq("order_id", order_id)
            .execute()
        )

        order_data = order_result.data[0]

        buyer = order_data.pop("buyer", None) or {}
        seller = order_data.pop("seller", None) or {}
        order_data["buyer_name"] = buyer.get("name")
        order_data["buyer_company"] = buyer.get("company_name")
        order_data["seller_name"] = seller.get("name")
        order_data["seller_company"] = seller.get("company_name")

        items_raw = items_result.data or []
        flat_items: list[dict] = []
        for item in items_raw:
            product = item.pop("products", None) or {}
            item["product_name"] = product.get("name")
            item["product_unit"] = product.get("unit")
            flat_items.append(item)

        order_data["items"] = flat_items
        order_data["items_count"] = len(flat_items)

        return {"success": True, "order": order_data}
    except Exception as e:
        return {"success": False, "error": str(e), "order": None}

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

def update_order_status(
    order_id: str = "",
    new_status: str = "",
    order_number: str = "",
) -> dict:
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

        # order_id가 없거나 UUID가 아니면 order_number로 주문 UUID를 찾는다.
        if not order_id or not _UUID_PATTERN.match(str(order_id)):
            if not order_number:
                return {
                    "success": False,
                    "llm_retry": True,
                    "error": (
                        "order_id가 UUID 형식이 아닙니다. "
                        "주문번호를 알고 있다면 order_number에 넣어 다시 호출하세요. "
                        "주문번호도 모르면 get_orders로 주문을 먼저 조회하세요."
                    ),
                }

            lookup = (
                supabase.table("orders")
                .select("id, order_number")
                .eq("order_number", order_number)
                .is_("deleted_at", None)
                .limit(1)
                .execute()
            )

            if not lookup.data:
                return {
                    "success": False,
                    "llm_retry": True,
                    "error": f"주문번호 '{order_number}'에 해당하는 주문을 찾을 수 없습니다.",
                }

            order_id = lookup.data[0]["id"]

        # 1. 주문 존재 여부와 현재 상태 확인
        order_check = (
            supabase.table("orders")
            .select("id, status")
            .eq("id", order_id)
            .is_("deleted_at", None)
            .execute()
        )

        if not order_check.data:
            return {
                "success": False,
                "error": "해당 주문을 찾을 수 없습니다.",
            }

        current_status = order_check.data[0].get("status")

        if current_status == new_status:
            return {
                "success": True,
                "already_same_status": True,
                "order_id": order_id,
                "previous_status": current_status,
                "new_status": new_status,
                "message": f"이미 {new_status} 상태인 주문입니다. 다른 주문을 대상으로 한 요청인지 확인이 필요합니다.",
            }
        
        # 2. 주문 확정 상태로 변경되는 순간 판매자 재고 차감
        #    이미 CONFIRMED였던 주문을 다시 CONFIRMED로 바꾸는 경우는 헬퍼 함수에서 중복 차감 방지
        inventory_result = None

        if new_status == "CONFIRMED":
            inventory_result = _deduct_seller_stock_for_order(
                supabase=supabase,
                order_id=order_id,
            )

            if not inventory_result.get("success"):
                return inventory_result

        # 3. 주문 상태 업데이트
        supabase.table("orders").update({"status": new_status}).eq("id", order_id).execute()

        # 4. 캘린더 동기화
        _sync_calendar_events_for_order_id(order_id)

        response = {
            "success": True,
            "order_id": order_id,
            "previous_status": current_status,
            "new_status": new_status,
        }

        if inventory_result is not None:
            response["inventory_deduction"] = inventory_result

        return response

    except Exception as e:
        return {"success": False, "error": str(e)}


def update_order(
    order_id: str,
    buyer_id: str,
    new_quantity: Optional[int] = None,
    new_unit_price: Optional[int] = None,
    delivery_date: Optional[str] = None,
    notes: Optional[str] = None,
    order_number: Optional[str] = None,
) -> dict:
    """주문 수량/단가/납품일/메모를 수정한다.
    order_id가 없으면 buyer_id + order_number로 검색.
    order_items의 subtotal과 orders의 total_amount도 자동 재계산.
    """
    try:
        supabase = get_supabase_client()

        # order_id가 없으면 order_number로 검색
        if not order_id or not _UUID_PATTERN.match(str(order_id)):
            if not order_number:
                return {"success": False, "error": "order_id 또는 order_number가 필요합니다."}
            res = (
                supabase.table("orders")
                .select("id, buyer_id")
                .eq("order_number", order_number)
                .is_("deleted_at", None)
                .limit(1)
                .execute()
            )
            if not res.data:
                return {"success": False, "error": f"주문 번호 '{order_number}'를 찾을 수 없습니다."}
            order_id = res.data[0]["id"]
            if buyer_id and res.data[0]["buyer_id"] != buyer_id:
                return {"success": False, "error": "권한 없음: 본인 주문만 수정할 수 있습니다."}

        # 주문 존재 확인
        order_check = supabase.table("orders").select("id, buyer_id, status").eq("id", order_id).is_("deleted_at", None).execute()
        if not order_check.data:
            return {"success": False, "error": "주문을 찾을 수 없습니다."}
        if buyer_id and order_check.data[0]["buyer_id"] != buyer_id:
            return {"success": False, "error": "권한 없음: 본인 주문만 수정할 수 있습니다."}

        # orders 테이블 업데이트 (납품일/메모)
        order_update: dict = {}
        if delivery_date is not None:
            order_update["delivery_date"] = delivery_date
        if notes is not None:
            order_update["notes"] = notes

        # order_items 수정 (수량/단가)
        if new_quantity is not None or new_unit_price is not None:
            items = supabase.table("order_items").select("id, quantity, unit_price").eq("order_id", order_id).execute()
            if items.data:
                item = items.data[0]
                qty = new_quantity if new_quantity is not None else item["quantity"]
                price = new_unit_price if new_unit_price is not None else item["unit_price"]
                subtotal = qty * price
                supabase.table("order_items").update({"quantity": qty, "unit_price": price, "subtotal": subtotal}).eq("id", item["id"]).execute()
                order_update["total_amount"] = subtotal

        if order_update:
            supabase.table("orders").update(order_update).eq("id", order_id).execute()
            _sync_calendar_events_for_order_id(order_id)

        return {"success": True, "order_id": order_id, "message": "주문이 수정되었습니다."}
    except Exception as e:
        return {"success": False, "error": str(e)}


def create_order(
    buyer_id: str,
    seller_id: str,
    product_id: str,
    quantity: int,
    unit_price: int,
    delivery_date: str,
    delivery_address: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    """새 주문을 생성한다 (AI 도우미 흐름 — auto_confirm=True 자동 협상 분기 적용).

    내부적으로 product_id 해석/검증을 마친 뒤 order_service.create_order(auto_confirm=True)
    에 위임한다. 라우터(POST /orders) 와 달리 자동 분기를 거치므로:
      - unit_price >= products.price_per_unit: QUOTE_REQUESTED 로 시작
        (판매자 검토 후 수락 시 CONFIRMED — 즉시 확정 아님)
      - unit_price <  products.price_per_unit: QUOTE_REQUESTED → 자동 카운터오퍼 → NEGOTIATING (PENDING 카드)

    delivery_date 는 필수 (V2, 2026-05-04). YYYY-MM-DD ISO 형식 문자열.
    product_id 가 UUID 가 아닌 상품명으로 들어온 경우 자동으로 이름 검색해 UUID 로 변환한다.
    """
    if not delivery_date or not isinstance(delivery_date, str) or not delivery_date.strip():
        return {
            "success": False,
            "error": "delivery_date 는 필수입니다. 사용자에게 납품일(YYYY-MM-DD)을 확인해주세요.",
        }
    try:
        supabase = get_supabase_client()

        # product_id가 UUID가 아니면 상품명으로 자동 검색
        if product_id and not _UUID_PATTERN.match(str(product_id)):
            found = _find_product_by_name(supabase, product_id, seller_id)
            if not found:
                return {"success": False, "error": f"'{product_id}' 상품을 찾을 수 없습니다. 상품명을 확인해주세요."}
            product_id = found["id"]
        elif product_id and _UUID_PATTERN.match(str(product_id)):
            # UUID가 맞더라도 해당 seller의 상품인지 검증
            verify = (
                supabase.table("products")
                .select("id, name, price_per_unit, unit")
                .eq("id", product_id)
                .eq("seller_id", seller_id)
                .is_("deleted_at", None)
                .execute()
            )
            if not verify.data:
                # seller 소속 상품이 아님 → 올바른 상품 찾아서 에러에 힌트 포함
                # seller 전체 상품 조회해서 힌트 제공
                all_products = (
                    supabase.table("products")
                    .select("id, name, price_per_unit, unit")
                    .eq("seller_id", seller_id)
                    .is_("deleted_at", None)
                    .limit(10)
                    .execute()
                )
                hint = ", ".join(
                    f"{p['name']}(id:{p['id']}, {p['price_per_unit']}원/{p['unit']})"
                    for p in (all_products.data or [])
                )
                return {
                    "success": False,
                    "llm_retry": True,
                    "error": (
                        f"product_id '{product_id}'는 seller_id '{seller_id}'의 상품이 아닙니다. "
                        f"이 판매자의 실제 상품 목록: [{hint}]. "
                        "올바른 product_id를 사용해 다시 create_order를 호출하세요."
                    ),
                }

        # order_service.create_order 호출용 payload 구성 (OrderCreate 스키마와 같은 키)
        from app.services.order_service import order_service

        order_payload: dict = {
            "seller_id": str(seller_id),
            "delivery_date": delivery_date,
            "delivery_address": delivery_address,
            "notes": notes,
            "items": [
                {
                    "product_id": str(product_id),
                    "quantity": int(quantity),
                    "unit_price": int(unit_price),
                    "notes": None,
                }
            ],
        }

        try:
            order = _run_async_in_thread(
                lambda: order_service.create_order(
                    buyer_id=buyer_id,
                    data=order_payload,
                    auto_confirm=True,  # AI 흐름 — 단가 비교 자동 분기 활성화
                )
            )
        except Exception as e:
            return _service_error_payload(e)

        order_id = str(order.get("id", ""))
        order_number = order.get("order_number", "")
        order_status = order.get("status", "QUOTE_REQUESTED")

        # 분기에 따른 안내 메시지 (LLM 자연어 응답 생성에 도움)
        # V2 (2026-05-04): 신규 주문은 항상 QUOTE_REQUESTED 또는 NEGOTIATING 으로 시작.
        # 가격 일치라도 즉시 CONFIRMED 되지 않고 판매자 검토 후 수락 시 CONFIRMED 전이.
        if order_status == "NEGOTIATING":
            human_message = (
                f"주문 {order_number}이 생성되어 자동 협상이 시작되었습니다. "
                f"채팅방에 카운터오퍼(PENDING) 카드가 노출되었습니다."
            )
            next_action_hint = (
                "사용자에게 협상 카드를 발송했음을 알리세요. 판매자가 수락/거절하기 전까지 PENDING."
            )
        else:
            # QUOTE_REQUESTED — UI 모달 흐름 + 단가 일치 (MATCH) 흐름 모두 포함
            human_message = (
                f"주문 견적 {order_number}이 판매자에게 전달됐습니다. 판매자 검토 후 확정됩니다."
            )
            next_action_hint = (
                "사용자에게 견적이 전달됐고 판매자 응답을 기다리는 중임을 안내하세요. "
                "사용자가 '채팅방 열어줘'라고 하면 open_chat_room 호출 시 반드시 이 order_id와 "
                "seller_id를 함께 사용하세요."
            )

        return {
            "success": True,
            "order": order,
            "order_id": order_id,
            "order_number": order_number,
            "status": order_status,
            # V2: CONFIRMED 자동 진입이 사라졌으므로 auto_confirmed 는 항상 False.
            # 호환성을 위해 키는 유지 — 외부 LLM 시스템 프롬프트가 점진적으로 마이그레이션될 때까지.
            "auto_confirmed": False,
            "negotiating": order_status == "NEGOTIATING",
            "seller_id": seller_id,
            "buyer_id": buyer_id,
            "product_id": product_id,
            "quantity": quantity,
            "unit_price": unit_price,
            "order_items": order.get("items") or [],
            "message": human_message,
            "next_action_hint": next_action_hint,
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

        # 결과가 없고 category가 ALL이 아니면 ALL로 재시도 (LLM이 잘못된 category를 추론한 경우 대비)
        if not products and category and category.upper() != "ALL":
            fallback_query = (
                supabase.table("products")
                .select("seller_id, name, price_per_unit, stock_quantity, unit, origin, spec, status, category")
            )
            if product_name:
                fallback_query = fallback_query.ilike("name", f"%{product_name}%")
            result = (
                fallback_query
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

        # products 테이블에서 해당 카테고리 상품 ID 먼저 조회 (soft delete 제외)
        prod_query = (
            supabase.table("products")
            .select("id, name, category")
            .is_("deleted_at", None)
        )
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
# 채팅방 도구
# ─────────────────────────────────────────────

def open_chat_room(user_id: str, partner_user_id: str, order_id: Optional[str] = None) -> dict:
    """두 사용자 간 채팅방을 조회하거나 생성한다.

    partner_user_id가 UUID 형식이 아니면 name/company_name으로 자동 검색해 UUID로 변환한다.

    보안 검증:
    1) self-chat 거부 (user_id == partner_user_id)
    2) partner 존재 + deleted_at IS NULL 확인 — 없으면 partner_not_found

    chat_rooms 테이블에서 역할에 따라 seller_id/buyer_id를 결정한다.

    주문별 채팅방 정책:
    - order_id가 있으면 seller_id + buyer_id + order_id 조합으로 방을 찾는다.
    - order_id가 없으면 seller_id + buyer_id + order_id IS NULL인 일반 채팅방만 찾는다.
    - 기존 일반 채팅방이나 다른 주문 채팅방에 order_id를 덮어쓰지 않는다.
    반환: {success, room_id, is_new, partner_name} 또는 {success: False, error, message?}
    """
    # partner_user_id가 UUID가 아니면 이름/회사명으로 자동 검색
    if not _UUID_PATTERN.match(str(partner_user_id)):
        try:
            _supabase = get_supabase_client()
            _r = (
                _supabase.table("users")
                .select("id")
                .or_(f"name.ilike.%{partner_user_id}%,company_name.ilike.%{partner_user_id}%")
                .is_("deleted_at", None)
                .limit(1)
                .execute()
            )
            if not _r.data:
                return {"success": False, "error": f"'{partner_user_id}' 사용자를 찾을 수 없습니다."}
            partner_user_id = _r.data[0]["id"]
        except Exception as _e:
            return {"success": False, "error": str(_e)}

    # 1) self-chat 거부
    if user_id == partner_user_id:
        return {
            "success": False,
            "error": "self_chat_not_allowed",
            "message": "자기 자신과는 채팅방을 만들 수 없습니다.",
        }

    try:
        supabase = get_supabase_client()

        # 2) partner 사용자 존재 + soft delete 확인
        partner_result = (
            supabase.table("users")
            .select("id, name, company_name, role")
            .eq("id", partner_user_id)
            .is_("deleted_at", None)
            .execute()
        )
        if not partner_result.data:
            return {
                "success": False,
                "error": "partner_not_found",
                "message": "상대방 사용자를 찾을 수 없습니다.",
            }
        partner = partner_result.data[0]
        partner_name = partner.get("name") or partner.get("company_name") or "알 수 없음"

        # 현재 사용자 역할 조회
        self_result = (
            supabase.table("users")
            .select("id, role")
            .eq("id", user_id)
            .is_("deleted_at", None)
            .execute()
        )
        if not self_result.data:
            return {"success": False, "error": "사용자 정보를 조회할 수 없습니다."}
        self_role = self_result.data[0].get("role", "BUYER")

        # 역할에 따라 seller_id / buyer_id 결정
        if self_role == "SELLER":
            seller_id, buyer_id = user_id, partner_user_id
        else:
            seller_id, buyer_id = partner_user_id, user_id

        if order_id:
            existing = (
                supabase.table("chat_rooms")
                .select("id")
                .eq("seller_id", seller_id)
                .eq("buyer_id", buyer_id)
                .eq("order_id", order_id)
                .execute()
            )
        else:
            existing = (
                supabase.table("chat_rooms")
                .select("id")
                .eq("seller_id", seller_id)
                .eq("buyer_id", buyer_id)
                .is_("order_id", None)
                .execute()
            )

        if existing.data:
            room_id = existing.data[0]["id"]
            return {
                "success": True,
                "room_id": room_id,
                "is_new": False,
                "partner_name": partner_name,
                "order_id": order_id,
            }

        # 새 채팅방 생성
        insert_payload: dict = {
            "seller_id": seller_id,
            "buyer_id": buyer_id,
        }

        if order_id:
            insert_payload["order_id"] = order_id

        created = (
            supabase.table("chat_rooms")
            .insert(insert_payload)
            .execute()
        )

        if not created.data:
            return {"success": False, "error": "채팅방 생성에 실패했습니다."}

        return {
            "success": True,
            "room_id": created.data[0]["id"],
            "is_new": True,
            "partner_name": partner_name,
            "order_id": order_id,
        }
    
    except Exception as e:
        return {"success": False, "error": str(e)}
    
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
# 캘린더 도구
# ─────────────────────────────────────────────
def get_calendar_events(user_id: str, year: int, month: int) -> dict:
    """해당 월의 캘린더 일정을 조회한다.
    날짜 범위: YYYY-MM-01 ~ YYYY-MM-{말일}
    deleted_at IS NULL 조건 적용 (BUG-1 패턴: .is_("deleted_at", None) 사용)

    응답 평탄화 (응답 우선순위 정책 — 상품명·거래처명·날짜·상태 메인):
    - product_name: 첫 활성 상품명 또는 "{첫 상품명} 외 N건"
    - order_number, order_status
    - buyer_name, buyer_company, seller_name, seller_company
    임베딩 객체(orders 등)는 응답에서 제거 — LLM 토큰 낭비 방지.
    반환: {success, events, count}
    """
    try:
        year_str = re.sub(r'\D', '', str(year))
        month_str = re.sub(r'\D', '', str(month))
        
        year = int(year_str) if year_str else datetime.now().year
        month = int(month_str) if month_str else datetime.now().month
        supabase = get_supabase_client()

        last_day = monthrange(year, month)[1]
        date_from = f"{year:04d}-{month:02d}-01"
        date_to = f"{year:04d}-{month:02d}-{last_day:02d}"

        result = (
            supabase.table("calendar_events")
            .select(
                "id, title, event_type, event_date, description, order_id, created_at, "
                "orders(order_number, status, "
                "buyer:users!buyer_id(name,company_name), "
                "seller:users!seller_id(name,company_name), "
                "order_items(quantity, products(name)))"
            )
            .eq("user_id", user_id)
            .gte("event_date", date_from)
            .lte("event_date", date_to)
            .is_("deleted_at", None)
            .order("event_date")
            .execute()
        )

        rows = result.data or []
        flattened: list[dict] = []
        for row in rows:
            order_payload = row.pop("orders", None)

            # 기본값
            row["order_number"] = None
            row["order_status"] = None
            row["product_name"] = None
            row["buyer_name"] = None
            row["buyer_company"] = None
            row["seller_name"] = None
            row["seller_company"] = None

            if isinstance(order_payload, dict):
                row["order_number"] = order_payload.get("order_number")
                row["order_status"] = order_payload.get("status")

                buyer = order_payload.get("buyer") or {}
                seller = order_payload.get("seller") or {}
                row["buyer_name"] = buyer.get("name")
                row["buyer_company"] = buyer.get("company_name")
                row["seller_name"] = seller.get("name")
                row["seller_company"] = seller.get("company_name")

                items = order_payload.get("order_items") or []
                product_names: list[str] = []
                for item in items:
                    product = item.get("products") if isinstance(item, dict) else None
                    if not product:
                        continue
                    name = product.get("name")
                    if name:
                        product_names.append(name)
                if product_names:
                    if len(product_names) == 1:
                        row["product_name"] = product_names[0]
                    else:
                        row["product_name"] = f"{product_names[0]} 외 {len(product_names) - 1}건"

            flattened.append(row)

        return {
            "success": True,
            "events": flattened,
            "count": len(flattened),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "events": [], "count": 0}


def create_calendar_event(
    user_id: str,
    title: str,
    event_date: str,
    event_type: str,
    description: str = "",
    order_id: str = "",
) -> dict:
    """캘린더 일정을 등록한다.
    event_type: SHIPMENT | DELIVERY | MEETING | QUOTE_DEADLINE | ORDER | OTHER
    event_date: "YYYY-MM-DD" 형식
    order_id가 빈 문자열이면 NULL로 저장한다.
    반환: {success, event_id, title}
    """
    # 1. 유효성 검사 (기존과 동일)
    VALID_EVENT_TYPES = {"SHIPMENT", "DELIVERY", "MEETING", "QUOTE_DEADLINE", "ORDER", "OTHER"}
    if event_type not in VALID_EVENT_TYPES:
        return {
            "success": False,
            "error": f"유효하지 않은 event_type입니다. 허용값: {', '.join(sorted(VALID_EVENT_TYPES))}",
        }

    try:
        supabase = get_supabase_client()

        # 🔥 [수정됨] order_id가 있다면 기존 일정이 있는지 확인하되, "event_type"도 같은지 확인!
        if order_id:
            existing = (
                supabase.table("calendar_events")
                .select("id")
                .eq("order_id", order_id)
                .eq("event_type", event_type)  
                .eq("user_id", user_id)
                .is_("deleted_at", None)  # 삭제되지 않은 것 중
                .execute()
            )

            # 같은 주문의 "같은 유형"의 일정이 이미 존재한다면? 새로 만들지 말고 업데이트!
            if existing.data:
                existing_event_id = existing.data[0]["id"]
                print(f"🕵️‍♂️ [System] 중복 일정 발견(ID: {existing_event_id}, 유형: {event_type}). 업데이트로 전환합니다.")
                
                return update_calendar_event(
                    user_id=user_id,
                    event_id=existing_event_id,
                    title=title,
                    event_date=event_date,
                    event_type=event_type,
                    description=description
                )

        # 2. 신규 등록 로직 (주문은 같아도 '배송', '출하' 등 유형이 다르면 이쪽으로 빠져서 새로 생성됨)
        payload: dict = {
            "user_id": user_id,
            "title": title,
            "event_date": event_date,
            "event_type": event_type,
            "description": description or None,
            "order_id": order_id if order_id else None,
        }

        result = supabase.table("calendar_events").insert(payload).execute()

        if not result.data:
            return {"success": False, "error": "일정 생성에 실패했습니다."}

        event = result.data[0]
        return {
            "success": True,
            "event_id": event["id"],
            "title": event.get("title", title),
            "message": "새로운 일정이 등록되었습니다."
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

def update_calendar_event(
    user_id: str,
    event_id: str,
    title: Optional[str] = None,
    event_date: Optional[str] = None,
    event_type: Optional[str] = None,
    description: Optional[str] = None,
) -> dict:
    """캘린더 일정을 수정한다."""
    VALID_EVENT_TYPES = {"SHIPMENT", "DELIVERY", "MEETING", "QUOTE_DEADLINE", "ORDER", "OTHER"}
    if event_type and event_type not in VALID_EVENT_TYPES:
        return {"success": False, "error": f"유효하지 않은 event_type입니다."}

    try:
        supabase = get_supabase_client()
        check = (
            supabase.table("calendar_events")
            .select("id, user_id, title, event_type, order_id")
            .eq("id", event_id)
            .is_("deleted_at", None)
            .execute()
        )
        if not check.data:
            return {"success": False, "error": "해당 일정을 찾을 수 없습니다."}
        if check.data[0]["user_id"] != user_id:
            return {"success": False, "error": "권한 없음: 본인의 일정만 수정할 수 있습니다."}

        # 주문 상태(ORDER) 이벤트는 시스템 동기화 대상이므로, 날짜/타입을 바꿔치기하는 업데이트를 금지한다.
        # (배송/납품 일정은 별도의 DELIVERY/SHIPMENT 이벤트로 새로 등록해야 함)
        existing = check.data[0]
        if existing.get("order_id") and existing.get("event_type") == "ORDER":
            if event_date is not None or (event_type is not None and event_type != "ORDER"):
                return {
                    "success": False,
                    "error": "주문 상태(ORDER) 일정은 날짜/유형을 변경할 수 없습니다. 배송 일정은 새 일정으로 등록하세요.",
                }

        update_data: dict = {}
        if title is not None: update_data["title"] = title
        if event_date is not None: update_data["event_date"] = event_date
        if event_type is not None: update_data["event_type"] = event_type
        if description is not None: update_data["description"] = description

        if not update_data:
            return {"success": False, "error": "수정할 내용이 없습니다."}

        supabase.table("calendar_events").update(update_data).eq("id", event_id).execute()
        return {"success": True, "event_id": event_id, "message": f"일정 '{existing['title']}'이(가) 수정되었습니다."}
    except Exception as e:
        return {"success": False, "error": str(e)}

def delete_calendar_event(user_id: str, event_id: str) -> dict:
    """캘린더 일정을 삭제한다 (soft delete)."""
    try:
        supabase = get_supabase_client()
        check = supabase.table("calendar_events").select("id, user_id, title").eq("id", event_id).is_("deleted_at", None).execute()
        if not check.data:
            return {"success": False, "error": "해당 일정을 찾을 수 없습니다."}
        if check.data[0]["user_id"] != user_id:
            return {"success": False, "error": "권한 없음: 본인의 일정만 삭제할 수 있습니다."}

        now_utc = datetime.now(timezone.utc).isoformat()
        supabase.table("calendar_events").update({"deleted_at": now_utc}).eq("id", event_id).execute()
        return {"success": True, "event_id": event_id, "message": f"일정 '{check.data[0]['title']}'이(가) 삭제되었습니다."}
    except Exception as e:
        return {"success": False, "error": str(e)}
    
# ─────────────────────────────────────────────
# 대체 거래처 탐색 도구
# ─────────────────────────────────────────────

def find_alternative_partners(
    user_id: str,
    role: str,
    category: str,
    reason: str = "",
) -> dict:
    """대체 거래처를 탐색한다.
    - BUYER 호출: products 테이블에서 해당 카테고리 보유 판매자 + partners 거래 이력(trade_count) 조인
      결과에 stock_quantity, price_per_unit 포함
    - SELLER 호출: orders 테이블에서 해당 카테고리 주문 이력 있는 구매자 + partners 거래 이력
    결과 정렬 공식 적용 금지 — LLM이 추천 순위/이유를 response_node에서 생성한다.
    DB 쿼리 최대 20건 제한.
    반환: {success, alternatives, count}
    """
    try:
        supabase = get_supabase_client()

        if role == "BUYER":
            # 해당 카테고리 상품을 보유한 판매자 목록 조회 (재고 있는 것만)
            prod_result = (
                supabase.table("products")
                .select("seller_id, name, stock_quantity, price_per_unit, unit, status, category")
                .eq("category", category.upper())
                .gt("stock_quantity", 0)
                .is_("deleted_at", None)
                .limit(20)
                .execute()
            )
            products = prod_result.data or []
            # 본인 제외 (BUYER 가 자기 자신을 다시 추천받지 않도록 — 단, role mismatch 시 의미 없음)
            seller_ids = list({
                p["seller_id"] for p in products
                if p.get("seller_id") and p["seller_id"] != user_id
            })

            if not seller_ids:
                return {"success": True, "alternatives": [], "count": 0}

            # 판매자 기본 정보 조회
            users_result = (
                supabase.table("users")
                .select("id, name, company_name, phone, email")
                .in_("id", seller_ids)
                .execute()
            )
            seller_map = {u["id"]: u for u in (users_result.data or [])}

            # orders 테이블에서 seller_id별 거래 건수 / 최근 거래일 동적 집계
            # (취소 제외, 삭제 제외, 최근 100건 제한)
            orders_result = (
                supabase.table("orders")
                .select("seller_id, created_at")
                .in_("seller_id", seller_ids)
                .neq("status", "CANCELLED")
                .is_("deleted_at", None)
                .order("created_at", desc=True)
                .limit(100)
                .execute()
            )
            # Python 단에서 seller_id별 집계
            trade_count_map: dict[str, int] = {}
            last_trade_map: dict[str, str] = {}
            for row in (orders_result.data or []):
                sid = row["seller_id"]
                trade_count_map[sid] = trade_count_map.get(sid, 0) + 1
                if sid not in last_trade_map:
                    last_trade_map[sid] = row["created_at"]

            # seller_id별 대표 상품 하나씩 선택 (stock 최대 기준)
            best_product: dict = {}
            for p in products:
                sid = p["seller_id"]
                if sid not in best_product or p["stock_quantity"] > best_product[sid]["stock_quantity"]:
                    best_product[sid] = p

            alternatives = []
            for sid in seller_ids:
                user_info = seller_map.get(sid, {})
                prod_info = best_product.get(sid, {})
                alternatives.append({
                    "user_id": sid,
                    "name": user_info.get("name", "알 수 없음"),
                    "company_name": user_info.get("company_name", ""),
                    "phone": user_info.get("phone", ""),
                    "email": user_info.get("email", ""),
                    "trade_count": trade_count_map.get(sid, 0),
                    "last_trade_date": last_trade_map.get(sid),
                    "stock_quantity": prod_info.get("stock_quantity", 0),
                    "price_per_unit": prod_info.get("price_per_unit", 0),
                    "unit": prod_info.get("unit", ""),
                    "product_name": prod_info.get("name", ""),
                })

        else:  # SELLER
            # 해당 카테고리 상품을 주문한 이력이 있는 구매자 목록
            prod_result = (
                supabase.table("products")
                .select("id")
                .eq("category", category.upper())
                .execute()
            )
            product_ids = [p["id"] for p in (prod_result.data or [])]
            if not product_ids:
                return {"success": True, "alternatives": [], "count": 0}

            items_result = (
                supabase.table("order_items")
                .select("order_id, orders!inner(buyer_id)")
                .in_("product_id", product_ids)
                .limit(100)
                .execute()
            )
            # 본인 제외 (SELLER 가 자기 자신을 추천받지 않도록 — 단, role mismatch 시 의미 없음)
            buyer_ids = list({
                item["orders"]["buyer_id"]
                for item in (items_result.data or [])
                if item.get("orders")
                and item["orders"].get("buyer_id")
                and item["orders"]["buyer_id"] != user_id
            })[:20]

            if not buyer_ids:
                return {"success": True, "alternatives": [], "count": 0}

            users_result = (
                supabase.table("users")
                .select("id, name, company_name, phone, email")
                .in_("id", buyer_ids)
                .execute()
            )
            buyer_map = {u["id"]: u for u in (users_result.data or [])}

            # orders 테이블에서 buyer_id별 거래 건수 / 최근 거래일 동적 집계
            # (취소 제외, 삭제 제외, 최근 100건 제한)
            orders_result = (
                supabase.table("orders")
                .select("buyer_id, created_at")
                .in_("buyer_id", buyer_ids)
                .neq("status", "CANCELLED")
                .is_("deleted_at", None)
                .order("created_at", desc=True)
                .limit(100)
                .execute()
            )
            # Python 단에서 buyer_id별 집계
            trade_count_map_b: dict[str, int] = {}
            last_trade_map_b: dict[str, str] = {}
            for row in (orders_result.data or []):
                bid = row["buyer_id"]
                trade_count_map_b[bid] = trade_count_map_b.get(bid, 0) + 1
                if bid not in last_trade_map_b:
                    last_trade_map_b[bid] = row["created_at"]

            alternatives = []
            for bid in buyer_ids:
                user_info = buyer_map.get(bid, {})
                alternatives.append({
                    "user_id": bid,
                    "name": user_info.get("name", "알 수 없음"),
                    "company_name": user_info.get("company_name", ""),
                    "phone": user_info.get("phone", ""),
                    "email": user_info.get("email", ""),
                    "trade_count": trade_count_map_b.get(bid, 0),
                    "last_trade_date": last_trade_map_b.get(bid),
                })

        return {
            "success": True,
            "alternatives": alternatives,
            "count": len(alternatives),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "alternatives": [], "count": 0}


# ─────────────────────────────────────────────
# 카운터오퍼 / 납품일 변경 도구 (LangGraph TEA 노드 → order_service async 메서드)
# ─────────────────────────────────────────────
#
# 모든 도구는 동기(sync) 함수이며, 내부적으로 별도 thread + 새 event loop 를
# 만들어 order_service 의 async 메서드를 호출한다 (orchestrator._execute_tool 이
# 이미 async 컨텍스트 안에서 sync 호출되기 때문에 asyncio.run() 직접 사용 시
# RuntimeError 위험 — concurrent.futures + asyncio.new_event_loop 패턴이 안전).
#
# service 메서드가 HTTPException 등을 raise 하면 도구는
# {"success": False, "error": ..., "code": <status>} 형태로 반환하여
# 다른 agent_tools 함수와 일관된 에러 포맷 유지.
#
# user 인자는 {"id": <user_uuid>} dict 만 만들어 넘긴다 (service 가 user["id"] 만 사용).

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


def submit_counter_offer(
    user_id: str = "",
    order_id: str = "",
    proposed_total_amount: int = 0,
    notes: Optional[str] = None,
) -> dict:
    """주문 카운터오퍼(가격 제시) 발송. 채팅방에 PENDING 상태 카드로 자동 노출됨.

    LLM 자연어 트리거 예: "1300000원으로 협상해줘", "13만원에 어때요", "가격 좀 깎아주세요".
    호출 즉시 상대방 채팅창에 수락/거절 버튼이 있는 COUNTER_OFFER 메시지 카드가 발송된다.
    이전 PENDING 카운터오퍼는 자동 SUPERSEDED 처리.

    파라미터:
      - user_id: 제시자 UUID (orchestrator._fix_id_params 가 항상 현재 user_id 강제 주입)
      - order_id: 대상 주문 UUID (필수). QUOTE_REQUESTED 또는 NEGOTIATING 상태여야 함.
      - proposed_total_amount: 제시 총 금액 (KRW 정수, 양수)
      - notes: 협상 메모 (선택)

    반환:
      성공: {success: True, offer: {...negotiation_history row...}}
      실패: {success: False, error: ..., code: <http_status>}
    """
    if not user_id or not _UUID_PATTERN.match(str(user_id)):
        return {"success": False, "error": "invalid_user_id"}
    if not order_id or not _UUID_PATTERN.match(str(order_id)):
        return {"success": False, "error": "invalid_order_id"}
    try:
        amount_int = int(proposed_total_amount)
    except (TypeError, ValueError):
        return {"success": False, "error": "proposed_total_amount must be an integer"}
    if amount_int <= 0:
        return {"success": False, "error": "proposed_total_amount must be > 0"}

    from app.services.order_service import order_service

    payload: dict = {"proposed_total_amount": amount_int}
    if notes:
        payload["notes"] = notes
    user_dict = {"id": str(user_id)}

    try:
        offer = _run_async_in_thread(
            lambda: order_service.submit_counter_offer(
                order_id=order_id, payload=payload, user=user_dict
            )
        )
        return {"success": True, "offer": offer}
    except Exception as e:
        return _service_error_payload(e)


def accept_counter_offer(
    user_id: str = "",
    order_id: str = "",
    offer_id: str = "",
) -> dict:
    """상대방의 PENDING 카운터오퍼를 수락. orders.total_amount, order_items 갱신 + 채팅 OFFER_ACCEPTED 카드 발송.

    LLM 자연어 트리거 예: "수락해줘", "OK", "그 가격으로 진행", "좋아요 그렇게 합시다".
    채팅방의 PENDING 카운터오퍼 카드 status 도 ACCEPTED 로 자동 동기화되어
    프론트의 수락/거절 버튼이 즉시 사라진다. 본인이 제시한 카운터오퍼는 수락 불가 (상대방만).

    반환:
      성공: {success: True, offer: {...accepted negotiation_history row...}}
      실패: {success: False, error: ..., code: <http_status>}
    """
    if not user_id or not _UUID_PATTERN.match(str(user_id)):
        return {"success": False, "error": "invalid_user_id"}
    if not order_id or not _UUID_PATTERN.match(str(order_id)):
        return {"success": False, "error": "invalid_order_id"}
    if not offer_id or not _UUID_PATTERN.match(str(offer_id)):
        return {"success": False, "error": "invalid_offer_id"}

    from app.services.order_service import order_service
    user_dict = {"id": str(user_id)}

    try:
        offer = _run_async_in_thread(
            lambda: order_service.accept_counter_offer(
                order_id=order_id, offer_id=offer_id, user=user_dict
            )
        )
        return {"success": True, "offer": offer}
    except Exception as e:
        return _service_error_payload(e)


def reject_counter_offer(
    user_id: str = "",
    order_id: str = "",
    offer_id: str = "",
) -> dict:
    """상대방의 PENDING 카운터오퍼를 거절. 채팅 OFFER_REJECTED 카드 발송.

    LLM 자연어 트리거 예: "거절해줘", "안 돼", "그 가격은 어렵습니다", "거절".
    채팅방의 PENDING 카드 status 도 REJECTED 로 자동 동기화. 본인 제시 카운터오퍼는 거절 불가.

    반환:
      성공: {success: True, offer: {...rejected negotiation_history row...}}
      실패: {success: False, error: ..., code: <http_status>}
    """
    if not user_id or not _UUID_PATTERN.match(str(user_id)):
        return {"success": False, "error": "invalid_user_id"}
    if not order_id or not _UUID_PATTERN.match(str(order_id)):
        return {"success": False, "error": "invalid_order_id"}
    if not offer_id or not _UUID_PATTERN.match(str(offer_id)):
        return {"success": False, "error": "invalid_offer_id"}

    from app.services.order_service import order_service
    user_dict = {"id": str(user_id)}

    try:
        offer = _run_async_in_thread(
            lambda: order_service.reject_counter_offer(
                order_id=order_id, offer_id=offer_id, user=user_dict
            )
        )
        return {"success": True, "offer": offer}
    except Exception as e:
        return _service_error_payload(e)


def submit_delivery_date_change(
    user_id: str = "",
    order_id: str = "",
    proposed_delivery_date: str = "",
    notes: Optional[str] = None,
) -> dict:
    """납품일 변경 요청 발송. 채팅방에 PENDING 카드로 자동 노출됨.

    LLM 자연어 트리거 예: "납품일 5월 10일로 바꿔줘", "배송일 변경 요청", "납기 다음 주 월요일로".
    호출 즉시 상대방 채팅창에 수락/거절 버튼이 있는 DELIVERY_DATE_CHANGE 메시지 카드가 발송된다.
    이전 PENDING 변경 요청은 자동 SUPERSEDED 처리.

    파라미터:
      - user_id: 요청자 UUID
      - order_id: 대상 주문 UUID. QUOTE_REQUESTED/NEGOTIATING/CONFIRMED 상태여야 함
                  (PREPARING 이상은 출하 준비 중이므로 차단됨).
      - proposed_delivery_date: 변경 희망일 (ISO YYYY-MM-DD). 오늘 이상이어야 함 (router 검증과 동일 정책).
      - notes: 변경 사유/메모 (선택)

    반환:
      성공: {success: True, change: {...delivery_date_change_history row...}}
      실패: {success: False, error: ..., code: <http_status>}
    """
    if not user_id or not _UUID_PATTERN.match(str(user_id)):
        return {"success": False, "error": "invalid_user_id"}
    if not order_id or not _UUID_PATTERN.match(str(order_id)):
        return {"success": False, "error": "invalid_order_id"}

    date_str = (proposed_delivery_date or "").strip()
    if not date_str:
        return {"success": False, "error": "proposed_delivery_date required (YYYY-MM-DD)"}
    try:
        proposed_date = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
    except ValueError:
        return {
            "success": False,
            "error": "proposed_delivery_date must be ISO date (YYYY-MM-DD)",
        }

    # KST 기준 오늘 이상 (router 와 동일 정책 — 과거 날짜 차단)
    from datetime import timedelta as _timedelta
    _kst_now = datetime.now(timezone(_timedelta(hours=9)))
    today_kst = _kst_now.date()
    if proposed_date < today_kst:
        return {
            "success": False,
            "error": "proposed_delivery_date must be today or later (KST)",
            "code": 422,
        }

    from app.services.order_service import order_service

    payload: dict = {"proposed_delivery_date": proposed_date.isoformat()}
    if notes:
        payload["notes"] = notes
    user_dict = {"id": str(user_id)}

    try:
        change = _run_async_in_thread(
            lambda: order_service.submit_delivery_date_change(
                order_id=order_id, payload=payload, user=user_dict
            )
        )
        return {"success": True, "change": change}
    except Exception as e:
        return _service_error_payload(e)


def accept_delivery_date_change(
    user_id: str = "",
    order_id: str = "",
    change_id: str = "",
) -> dict:
    """상대방의 PENDING 납품일 변경 요청을 수락. orders.delivery_date 갱신 + 캘린더 재동기화.

    LLM 자연어 트리거 예: "수락해줘", "OK", "그 날짜로 좋아요", "납품일 변경 동의".
    채팅 DELIVERY_DATE_ACCEPTED 카드 발송 + PENDING 카드 status → ACCEPTED 자동 동기화.
    양 당사자 캘린더가 새 납품일로 자동 이동(옛 event_date row 는 soft-delete).
    본인 제시 변경 요청은 수락 불가 (상대방만).

    반환:
      성공: {success: True, change: {...accepted delivery_date_change row...}}
      실패: {success: False, error: ..., code: <http_status>}
    """
    if not user_id or not _UUID_PATTERN.match(str(user_id)):
        return {"success": False, "error": "invalid_user_id"}
    if not order_id or not _UUID_PATTERN.match(str(order_id)):
        return {"success": False, "error": "invalid_order_id"}
    if not change_id or not _UUID_PATTERN.match(str(change_id)):
        return {"success": False, "error": "invalid_change_id"}

    from app.services.order_service import order_service
    user_dict = {"id": str(user_id)}

    try:
        change = _run_async_in_thread(
            lambda: order_service.accept_delivery_date_change(
                order_id=order_id, change_id=change_id, user=user_dict
            )
        )
        return {"success": True, "change": change}
    except Exception as e:
        return _service_error_payload(e)


def reject_delivery_date_change(
    user_id: str = "",
    order_id: str = "",
    change_id: str = "",
) -> dict:
    """상대방의 PENDING 납품일 변경 요청을 거절. 채팅 DELIVERY_DATE_REJECTED 카드 발송.

    LLM 자연어 트리거 예: "거절해줘", "안 돼", "그 날짜는 어려워요", "납품일 변경 거부".
    채팅방의 PENDING 카드 status 도 REJECTED 로 자동 동기화. 본인 제시 변경 요청은 거절 불가.

    반환:
      성공: {success: True, change: {...rejected delivery_date_change row...}}
      실패: {success: False, error: ..., code: <http_status>}
    """
    if not user_id or not _UUID_PATTERN.match(str(user_id)):
        return {"success": False, "error": "invalid_user_id"}
    if not order_id or not _UUID_PATTERN.match(str(order_id)):
        return {"success": False, "error": "invalid_order_id"}
    if not change_id or not _UUID_PATTERN.match(str(change_id)):
        return {"success": False, "error": "invalid_change_id"}

    from app.services.order_service import order_service
    user_dict = {"id": str(user_id)}

    try:
        change = _run_async_in_thread(
            lambda: order_service.reject_delivery_date_change(
                order_id=order_id, change_id=change_id, user=user_dict
            )
        )
        return {"success": True, "change": change}
    except Exception as e:
        return _service_error_payload(e)


# ─────────────────────────────────────────────
# 사용자 프로필 조회 도구
# ─────────────────────────────────────────────

def get_user_profile(
    user_id: str = "",
    username: str = "",
    company_name: str = "",
) -> dict:
    """사용자 프로필을 조회한다.
    user_id, username, company_name 중 적어도 하나 필요.
    user_service.py의 get_user_profile / search_users 로직을 직접 재현한다
    (asyncio.to_thread 없이 동기 호출, Supabase 중복 구현 금지 원칙에 따라
     user_service 인스턴스 직접 import하지 않고 동일 Supabase 클라이언트만 사용).
    반환: {success, user: {id, username, role, company_name, phone, email, ...}}
    못 찾으면: {success: False, error: "user_not_found"}
    """
    if not user_id and not username and not company_name:
        return {"success": False, "error": "user_id, username, company_name 중 하나 이상 필요합니다."}

    COLUMNS = "id, email, name, role, company_name, phone, profile_image, is_active, created_at"

    try:
        supabase = get_supabase_client()

        # 1순위: user_id로 직접 조회
        if user_id:
            result = (
                supabase.table("users")
                .select(COLUMNS)
                .eq("id", user_id)
                .eq("is_active", True)
                .is_("deleted_at", None)
                .execute()
            )
            if result.data:
                return {"success": True, "user": result.data[0]}

        # 2순위: username(name 컬럼) 검색
        if username:
            result = (
                supabase.table("users")
                .select(COLUMNS)
                .ilike("name", f"%{username}%")
                .eq("is_active", True)
                .is_("deleted_at", None)
                .limit(1)
                .execute()
            )
            if result.data:
                return {"success": True, "user": result.data[0]}

        # 3순위: company_name 검색
        if company_name:
            result = (
                supabase.table("users")
                .select(COLUMNS)
                .ilike("company_name", f"%{company_name}%")
                .eq("is_active", True)
                .is_("deleted_at", None)
                .limit(1)
                .execute()
            )
            if result.data:
                return {"success": True, "user": result.data[0]}

        return {"success": False, "error": "user_not_found"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ─────────────────────────────────────────────
# 거래처 등록 도구 (양방향 PENDING — V1.6)
# ─────────────────────────────────────────────


def _build_partner_response(supabase, partner_row: dict) -> dict:
    """본인 row 에 partner_user 임베딩(name/company_name/role/phone)을 붙여 반환.

    partner_service.create_partner 의 응답 형식과 동일하게 맞춘다.
    임베딩 조회 실패 시에는 partner_row 만 반환 (best-effort).
    """
    partner_id = partner_row.get("id")
    if not partner_id:
        return partner_row

    try:
        result = (
            supabase.table("partners")
            .select(
                "*, partner_user:users!partner_user_id(name, company_name, role, phone)"
            )
            .eq("id", partner_id)
            .single()
            .execute()
        )
        row = result.data or partner_row
    except Exception:
        row = partner_row

    partner_user = row.pop("partner_user", None) or {}
    row["partner_name"] = partner_user.get("name")
    row["partner_company"] = partner_user.get("company_name")
    row["partner_role"] = partner_user.get("role")
    row["partner_phone"] = partner_user.get("phone")
    return row


def request_partner_registration(
    user_id: str,
    target_user_id: str,
    note: Optional[str] = None,
) -> dict:
    """거래처 등록 요청을 상대방에게 보낸다 (양방향 PENDING).

    이 도구는 상대방 사용자 UUID 가 정확히 알려진 경우에만 호출한다.
    이름/회사명만 알면 먼저 request_partner_registration_by_name 도구를 사용하거나,
    get_user_profile 로 UUID 를 조회한 뒤 호출하라.

    동작 (partner_service.create_partner 와 동일):
      - 본인 row(PENDING_OUTGOING) + 상대 row(PENDING_INCOMING) 두 row 동시 INSERT
      - 상대가 POST /partners/{id}/accept 호출 시 양쪽 ACTIVE 로 전환
      - notes 는 본인 row 에만 적용 (상대 row 는 빈 값)

    반환:
      - 성공: {"success": True, "partner_id": "...", "status": "PENDING_OUTGOING",
              "partner_name": "...", "partner_company": "...", "message": "..."}
      - 자기 자신: {"success": False, "error": "self_registration_not_allowed", ...}
      - 이미 등록됨/요청 중: {"success": False, "error": "already_partner", ...}
      - 상대방 없음: {"success": False, "error": "user_not_found", ...}
    """
    # 입력 검증
    user_id_str = (user_id or "").strip()
    target_id_str = (target_user_id or "").strip()

    if not user_id_str or not _UUID_PATTERN.match(user_id_str):
        return {
            "success": False,
            "error": "invalid_user_id",
            "detail": "요청자 UUID 가 유효하지 않습니다.",
        }
    if not target_id_str or not _UUID_PATTERN.match(target_id_str):
        return {
            "success": False,
            "error": "invalid_target_user_id",
            "detail": (
                "상대방 UUID 가 유효하지 않습니다. "
                "이름/회사명으로만 알고 있다면 request_partner_registration_by_name 도구를 사용하세요."
            ),
        }

    # 자기 자신 거래처 등록 차단
    if user_id_str == target_id_str:
        return {
            "success": False,
            "error": "self_registration_not_allowed",
            "detail": "자기 자신을 거래처로 등록할 수 없습니다.",
        }

    try:
        supabase = get_supabase_client()

        # 상대방 존재 + soft-delete 확인
        target_result = (
            supabase.table("users")
            .select("id, name, company_name, role")
            .eq("id", target_id_str)
            .is_("deleted_at", None)
            .limit(1)
            .execute()
        )
        if not target_result.data:
            return {
                "success": False,
                "error": "user_not_found",
                "detail": "상대방 사용자를 찾을 수 없습니다.",
            }
        target = target_result.data[0]
        target_name = target.get("name") or target.get("company_name") or "상대방"

        # 기존 active row(ACTIVE / PENDING_*) 사전 체크 — partial unique index 충돌 방지
        existing = (
            supabase.table("partners")
            .select("id, status")
            .eq("user_id", user_id_str)
            .eq("partner_user_id", target_id_str)
            .is_("deleted_at", None)
            .limit(1)
            .execute()
        )
        if existing.data:
            existing_row = existing.data[0]
            return {
                "success": False,
                "error": "already_partner",
                "detail": (
                    f"이미 거래처입니다 (status={existing_row.get('status')}). "
                    "거래처 목록에서 확인해 주세요."
                ),
                "partner_id": existing_row.get("id"),
                "partner_status": existing_row.get("status"),
            }

        # 본인 row INSERT (PENDING_OUTGOING)
        outgoing_payload = {
            "user_id": user_id_str,
            "partner_user_id": target_id_str,
            "status": "PENDING_OUTGOING",
            "notes": note,
        }
        try:
            outgoing_result = (
                supabase.table("partners").insert(outgoing_payload).execute()
            )
        except Exception as e:
            err_msg = str(e)
            if "23505" in err_msg or "duplicate" in err_msg.lower():
                return {
                    "success": False,
                    "error": "already_partner",
                    "detail": "이미 등록되었거나 요청 중인 거래처입니다.",
                }
            return {
                "success": False,
                "error": "insert_failed",
                "detail": f"본인 row INSERT 실패: {type(e).__name__}: {e}",
            }

        if not outgoing_result.data:
            return {
                "success": False,
                "error": "insert_failed",
                "detail": "본인 row INSERT 결과가 비어있습니다.",
            }
        outgoing_row = outgoing_result.data[0]
        outgoing_id = outgoing_row["id"]

        # 상대 row INSERT (PENDING_INCOMING) — 실패 시 본인 row hard-delete 보상
        incoming_payload = {
            "user_id": target_id_str,
            "partner_user_id": user_id_str,
            "status": "PENDING_INCOMING",
        }
        try:
            incoming_result = (
                supabase.table("partners").insert(incoming_payload).execute()
            )
            if not incoming_result.data:
                raise RuntimeError("상대 row INSERT 결과가 비어있습니다.")
        except Exception as e:
            # 보상: 본인 row hard-delete
            try:
                supabase.table("partners").delete().eq("id", outgoing_id).execute()
            except Exception as rollback_err:
                print(
                    f"[request_partner_registration] rollback 실패 "
                    f"outgoing_id={outgoing_id}: "
                    f"{type(rollback_err).__name__}: {rollback_err}"
                )
            err_msg = str(e)
            if "23505" in err_msg or "duplicate" in err_msg.lower():
                return {
                    "success": False,
                    "error": "already_partner",
                    "detail": "상대방과 이미 거래처 관계가 존재합니다.",
                }
            return {
                "success": False,
                "error": "insert_failed",
                "detail": f"상대 row INSERT 실패: {type(e).__name__}: {e}",
            }

        # 응답 — partner_user 임베딩 포함
        enriched = _build_partner_response(supabase, outgoing_row)

        return {
            "success": True,
            "partner_id": enriched.get("id"),
            "status": enriched.get("status", "PENDING_OUTGOING"),
            "partner_name": enriched.get("partner_name") or target_name,
            "partner_company": enriched.get("partner_company"),
            "partner_role": enriched.get("partner_role"),
            "message": (
                f"{target_name} 님에게 거래처 등록 요청을 보냈습니다. "
                "상대가 수락하면 거래처 목록에 활성 상태로 표시됩니다."
            ),
        }

    except Exception as e:
        return {
            "success": False,
            "error": "unexpected_error",
            "detail": f"{type(e).__name__}: {e}",
        }


def request_partner_registration_by_name(
    user_id: str,
    target_name_or_company: str,
    note: Optional[str] = None,
) -> dict:
    """이름/회사명으로 거래처 등록 요청.

    내부적으로 사용자를 검색해 단일 매칭이면 즉시 신청, 다중 매칭이면
    confirmation 응답을 반환한다 (send_chat_message 의 needs_confirmation 패턴).

    검색 조건:
      - users.name ilike '%{target}%' 또는 company_name ilike '%{target}%'
      - is_active=true, deleted_at IS NULL
      - 본인 제외

    반환:
      - 단일 매칭 + 신청 성공: request_partner_registration 응답과 동일
      - 다중 매칭: {"success": False, "needs_confirmation": True,
                  "candidates": [{user_id, name, company_name, role}, ...]}
      - 0건: {"success": False, "error": "no_match", "detail": "○○ 님을 찾을 수 없습니다"}
      - 자기 자신 매칭: {"success": False, "error": "self_registration_not_allowed", ...}
    """
    user_id_str = (user_id or "").strip()
    query_str = (target_name_or_company or "").strip()

    if not user_id_str or not _UUID_PATTERN.match(user_id_str):
        return {
            "success": False,
            "error": "invalid_user_id",
            "detail": "요청자 UUID 가 유효하지 않습니다.",
        }
    if not query_str:
        return {
            "success": False,
            "error": "missing_target",
            "detail": "거래처로 등록할 상대방의 이름이나 회사명을 알려주세요.",
        }

    try:
        supabase = get_supabase_client()

        # 이름/회사명 OR 검색 (본인 제외)
        result = (
            supabase.table("users")
            .select("id, name, company_name, role")
            .or_(
                f"name.ilike.%{query_str}%,"
                f"company_name.ilike.%{query_str}%"
            )
            .neq("id", user_id_str)
            .eq("is_active", True)
            .is_("deleted_at", None)
            .limit(10)
            .execute()
        )
        candidates = result.data or []

        if not candidates:
            return {
                "success": False,
                "error": "no_match",
                "detail": f"'{query_str}' 님을 찾을 수 없습니다.",
            }

        if len(candidates) >= 2:
            return {
                "success": False,
                "needs_confirmation": True,
                "candidates": [
                    {
                        "user_id": c["id"],
                        "name": c.get("name"),
                        "company_name": c.get("company_name"),
                        "role": c.get("role"),
                    }
                    for c in candidates
                ],
                "message": (
                    f"'{query_str}' 와 일치하는 사용자가 {len(candidates)} 명 있습니다. "
                    "어느 분을 거래처로 등록할지 확인 후 user_id 를 직접 지정해 "
                    "request_partner_registration 도구로 다시 호출하세요."
                ),
            }

        # 단일 매칭 → 즉시 신청
        target = candidates[0]
        return request_partner_registration(
            user_id=user_id_str,
            target_user_id=target["id"],
            note=note,
        )

    except Exception as e:
        return {
            "success": False,
            "error": "unexpected_error",
            "detail": f"{type(e).__name__}: {e}",
        }


# ─────────────────────────────────────────────
# 채팅 합의 감지 (chat_ws.py 전용 — TOOL_FUNCTION_MAP 미등록)
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
# 정기배송(Subscription) 관련 도구
# ─────────────────────────────────────────────
# 참고:
#   - 실제 INSERT/UPDATE 비즈니스 로직은 app/services/subscription_service.py 에 구현되어 있다.
#     본 도구들은 LLM tool-use 호환 입력(자연어 친화)을 받아 검증한 뒤 그 서비스를 호출한다.
#   - sync 도구로 등록하기 위해 _run_async_in_thread 로 비동기 서비스 함수를 실행한다
#     (이미 검증된 헬퍼; 협상/배송 변경 도구들과 동일 패턴).

_SUBSCRIPTION_FREQUENCIES = ("WEEKLY", "BIWEEKLY", "MONTHLY")
_SUBSCRIPTION_FREQ_KO = {
    "매주": "WEEKLY",
    "주간": "WEEKLY",
    "주 1회": "WEEKLY",
    "주1회": "WEEKLY",
    "격주": "BIWEEKLY",
    "2주": "BIWEEKLY",
    "2주마다": "BIWEEKLY",
    "월": "MONTHLY",
    "월간": "MONTHLY",
    "매월": "MONTHLY",
    "한달": "MONTHLY",
    "월1회": "MONTHLY",
    "월 1회": "MONTHLY",
}
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _normalize_frequency(value: Optional[str]) -> Optional[str]:
    """LLM 이 넘긴 frequency 문자열을 표준 코드로 변환. 표준값이 아니면 None."""
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    upper = s.upper()
    if upper in _SUBSCRIPTION_FREQUENCIES:
        return upper
    return _SUBSCRIPTION_FREQ_KO.get(s)


def _normalize_iso_date(value: Optional[str]) -> Optional[str]:
    """YYYY-MM-DD 형태로 정규화. 형식 안 맞으면 None."""
    if not value:
        return None
    s = str(value).strip()[:10]
    if _DATE_PATTERN.match(s):
        return s
    return None


def _resolve_subscription_items(
    supabase,
    *,
    seller_id: str,
    items: list[dict],
) -> tuple[list[dict], list[str]]:
    """LLM 입력 items 를 subscription_service 가 요구하는 dict 리스트로 정규화.

    각 입력 item 은 다음 키를 가질 수 있다:
      - product_id   (UUID, 권장)
      - product_name (UUID 모를 때 사용 — seller_id 범위에서 자동 검색)
      - quantity     (int > 0)
      - unit_price   (int >= 0; 미지정 시 product.price_per_unit 자동 채움)
      - unit         (kg/box/piece 등; 미지정 시 product.unit 자동 채움)

    반환: (정규화된 items 리스트, 에러 메시지 리스트)
      에러가 있으면 호출 측에서 needs_clarification 응답 구성에 사용.
    """
    resolved: list[dict] = []
    errors: list[str] = []

    if not isinstance(items, list) or not items:
        return resolved, ["items 가 비어 있습니다. 정기배송할 품목/수량/단가를 1개 이상 알려주세요."]

    for idx, raw in enumerate(items):
        if not isinstance(raw, dict):
            errors.append(f"items[{idx}] 형식이 잘못되었습니다 (dict 가 아님).")
            continue

        product_id = (raw.get("product_id") or "").strip()
        product_name = (raw.get("product_name") or "").strip()
        product_row: Optional[dict] = None

        if product_id and _UUID_PATTERN.match(product_id):
            try:
                q = (
                    supabase.table("products")
                    .select("id, name, unit, price_per_unit")
                    .eq("id", product_id)
                    .is_("deleted_at", None)
                )
                if seller_id:
                    q = q.eq("seller_id", seller_id)
                vr = q.execute()
                if not vr.data:
                    errors.append(
                        f"items[{idx}] product_id '{product_id}' 가 판매자 상품에서 확인되지 않습니다."
                    )
                    continue
                product_row = vr.data[0]
            except Exception as e:
                errors.append(f"items[{idx}] 상품 조회 오류: {e}")
                continue
        elif product_name:
            found = _find_product_by_name(supabase, product_name, seller_id)
            if not found:
                errors.append(f"items[{idx}] '{product_name}' 상품을 찾을 수 없습니다.")
                continue
            product_id = found["id"]
            try:
                detail = (
                    supabase.table("products")
                    .select("id, name, unit, price_per_unit")
                    .eq("id", product_id)
                    .is_("deleted_at", None)
                    .execute()
                )
                product_row = detail.data[0] if detail.data else found
            except Exception:
                product_row = found
        else:
            errors.append(f"items[{idx}] product_id 또는 product_name 중 하나는 필요합니다.")
            continue

        try:
            quantity = int(raw.get("quantity"))
        except (TypeError, ValueError):
            errors.append(f"items[{idx}] quantity 가 정수가 아닙니다.")
            continue
        if quantity <= 0:
            errors.append(f"items[{idx}] quantity 는 1 이상이어야 합니다.")
            continue

        unit_price_raw = raw.get("unit_price")
        unit_price: Optional[int] = None
        if unit_price_raw is not None and unit_price_raw != "":
            try:
                unit_price = int(unit_price_raw)
            except (TypeError, ValueError):
                errors.append(f"items[{idx}] unit_price 가 정수가 아닙니다.")
                continue
        if unit_price is None and product_row:
            unit_price = product_row.get("price_per_unit")
        if unit_price is None:
            errors.append(f"items[{idx}] unit_price 가 누락되었습니다.")
            continue
        if unit_price < 0:
            errors.append(f"items[{idx}] unit_price 는 0 이상이어야 합니다.")
            continue

        unit = (raw.get("unit") or "").strip()
        if not unit and product_row:
            unit = product_row.get("unit") or ""
        if not unit:
            errors.append(f"items[{idx}] unit 이 누락되었습니다.")
            continue

        resolved.append({
            "product_id": product_id,
            "quantity": quantity,
            "unit_price": unit_price,
            "unit": unit,
        })

    return resolved, errors


def create_subscription_request(
    user_id: str = "",
    target_user_id: str = "",
    frequency: str = "",
    start_date: str = "",
    end_date: Optional[str] = None,
    items: Optional[list[dict]] = None,
    delivery_address: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    """정기배송 요청을 상대방에게 보낸다 (status=PENDING 으로 시작).

    상대방이 accept 하면 ACTIVE, reject 하면 REJECTED 로 전환된다.
    필수 정보(frequency / start_date / items) 가 부족하면
    needs_clarification=True 응답을 돌려 LLM 이 사용자에게 다시 묻도록 한다.

    파라미터:
      user_id: 현재 로그인 사용자 UUID (요청자, created_by 로 저장됨)
      target_user_id: 정기배송 상대방 UUID
      frequency: WEEKLY / BIWEEKLY / MONTHLY (한국어 '매주'/'격주'/'매월' 도 허용)
      start_date: YYYY-MM-DD
      end_date: YYYY-MM-DD (선택)
      items: [{product_id|product_name, quantity, unit_price?, unit?}, ...]
      delivery_address: 납품 주소 (선택)
      notes: 메모 (선택)

    반환:
      성공: {success: True, subscription_id, status: "PENDING", direction, message}
      검증 실패: {success: False, needs_clarification: True, missing: [...], message}
      서비스 실패: {success: False, error, message}
    """
    user_clean = (user_id or "").strip()
    target_clean = (target_user_id or "").strip()

    if not user_clean or not _UUID_PATTERN.match(user_clean):
        return {"success": False, "error": "invalid_user_id", "message": "현재 사용자 UUID 가 유효하지 않습니다."}
    if not target_clean or not _UUID_PATTERN.match(target_clean):
        return {
            "success": False,
            "needs_clarification": True,
            "missing": ["target_user_id"],
            "message": "정기배송을 누구에게 요청할지 알려주세요. (거래처 이름이나 회사명을 알려주시면 자동으로 찾아드립니다.)",
        }
    if user_clean == target_clean:
        return {
            "success": False,
            "error": "self_subscription_not_allowed",
            "message": "자기 자신에게 정기배송을 요청할 수 없습니다.",
        }

    missing: list[str] = []
    freq_norm = _normalize_frequency(frequency)
    if not freq_norm:
        missing.append("frequency")
    start_norm = _normalize_iso_date(start_date)
    if not start_norm:
        missing.append("start_date")

    end_norm = _normalize_iso_date(end_date) if end_date else None
    if end_date and not end_norm:
        return {
            "success": False,
            "needs_clarification": True,
            "missing": ["end_date"],
            "message": "end_date 는 YYYY-MM-DD 형식이어야 합니다.",
        }

    if missing:
        msg_parts: list[str] = []
        if "frequency" in missing:
            msg_parts.append("배송 주기(매주/격주/매월)")
        if "start_date" in missing:
            msg_parts.append("시작 날짜(YYYY-MM-DD)")
        return {
            "success": False,
            "needs_clarification": True,
            "missing": missing,
            "message": "정기배송을 등록하려면 " + " 와 ".join(msg_parts) + " 가 필요합니다. 알려주세요.",
        }

    # 역할 매칭 — SELLER↔BUYER 만 허용. seller_id, buyer_id 결정.
    try:
        supabase = get_supabase_client()
        me_result = (
            supabase.table("users")
            .select("id, role")
            .eq("id", user_clean)
            .is_("deleted_at", None)
            .limit(1)
            .execute()
        )
        if not me_result.data:
            return {"success": False, "error": "user_not_found", "message": "현재 사용자 정보를 찾을 수 없습니다."}
        my_role = (me_result.data[0].get("role") or "").upper()

        target_result = (
            supabase.table("users")
            .select("id, role, name, company_name")
            .eq("id", target_clean)
            .is_("deleted_at", None)
            .limit(1)
            .execute()
        )
        if not target_result.data:
            return {
                "success": False,
                "error": "target_not_found",
                "message": "정기배송 상대방을 찾을 수 없습니다.",
            }
        target_role = (target_result.data[0].get("role") or "").upper()
        target_label = (
            target_result.data[0].get("company_name")
            or target_result.data[0].get("name")
            or "거래처"
        )
    except Exception as e:
        return {"success": False, "error": str(e)}

    if my_role == "SELLER" and target_role == "BUYER":
        seller_id, buyer_id = user_clean, target_clean
        direction = "SELLER_TO_BUYER"
    elif my_role == "BUYER" and target_role == "SELLER":
        seller_id, buyer_id = target_clean, user_clean
        direction = "BUYER_TO_SELLER"
    else:
        return {
            "success": False,
            "error": "role_mismatch",
            "message": (
                "정기배송은 판매자(SELLER) 와 구매자(BUYER) 간에만 등록할 수 있습니다. "
                f"(나={my_role or '?'}, 상대={target_role or '?'})"
            ),
        }

    resolved_items, item_errors = _resolve_subscription_items(
        supabase, seller_id=seller_id, items=items or []
    )
    if not resolved_items:
        return {
            "success": False,
            "needs_clarification": True,
            "missing": ["items"],
            "message": (
                "정기배송할 품목/수량/단가를 알려주세요.\n"
                + ("\n".join(f"- {e}" for e in item_errors) if item_errors else "예) '망고 2box, 단가 30000원'")
            ),
        }

    from app.services.subscription_service import subscription_service
    from uuid import UUID as _UUID

    payload = {
        "seller_id": seller_id,
        "buyer_id": buyer_id,
        "frequency": freq_norm,
        "start_date": start_norm,
        "end_date": end_norm,
        "delivery_address": delivery_address,
        "notes": notes,
        "items": resolved_items,
    }

    try:
        sub = _run_async_in_thread(
            lambda: subscription_service.create_subscription(
                user_id=_UUID(user_clean), payload=payload
            )
        )
    except Exception as e:
        return _service_error_payload(e)

    return {
        "success": True,
        "subscription_id": sub.get("id") if isinstance(sub, dict) else None,
        "status": sub.get("status") if isinstance(sub, dict) else "PENDING",
        "direction": direction,
        "frequency": freq_norm,
        "start_date": start_norm,
        "end_date": end_norm,
        "items_count": len(resolved_items),
        "target_label": target_label,
        "message": (
            f"{target_label} 에게 정기배송 요청을 보냈습니다 (주기: {freq_norm}, 시작: {start_norm}). "
            "상대방이 수락하면 자동으로 활성화됩니다."
        ),
    }


def accept_subscription_request(user_id: str = "", subscription_id: str = "") -> dict:
    """받은 정기배송 요청을 수락한다 (PENDING → ACTIVE).

    - 요청자 본인은 수락 불가 (subscription_service 에서 403).
    - status 가 PENDING 이 아니면 400.
    - ACTIVE 전환 시 양 당사자 캘린더에 다음 배송 일정이 자동 등록된다.
    """
    user_clean = (user_id or "").strip()
    sub_clean = (subscription_id or "").strip()

    if not user_clean or not _UUID_PATTERN.match(user_clean):
        return {"success": False, "error": "invalid_user_id", "message": "현재 사용자 UUID 가 유효하지 않습니다."}
    if not sub_clean or not _UUID_PATTERN.match(sub_clean):
        return {
            "success": False,
            "needs_clarification": True,
            "missing": ["subscription_id"],
            "message": "수락할 정기배송 ID 를 알려주세요. (정기배송 목록에서 확인)",
        }

    from app.services.subscription_service import subscription_service
    from uuid import UUID as _UUID

    try:
        sub = _run_async_in_thread(
            lambda: subscription_service.accept_subscription(
                subscription_id=_UUID(sub_clean), user_id=_UUID(user_clean)
            )
        )
    except Exception as e:
        return _service_error_payload(e)

    return {
        "success": True,
        "subscription_id": sub.get("id") if isinstance(sub, dict) else sub_clean,
        "status": sub.get("status") if isinstance(sub, dict) else "ACTIVE",
        "next_delivery_date": sub.get("next_delivery_date") if isinstance(sub, dict) else None,
        "message": "정기배송 요청을 수락했습니다. 캘린더에 다음 배송 일정이 자동 등록됩니다.",
    }


def reject_subscription_request(
    user_id: str = "",
    subscription_id: str = "",
    reason: Optional[str] = None,
) -> dict:
    """받은 정기배송 요청을 거절한다 (PENDING → REJECTED).

    - 요청자 본인은 거절 불가.
    - reason 은 현재 DB 컬럼이 없어 응답 메시지에만 활용된다 (이력 보존은 status=REJECTED 로).
    """
    user_clean = (user_id or "").strip()
    sub_clean = (subscription_id or "").strip()

    if not user_clean or not _UUID_PATTERN.match(user_clean):
        return {"success": False, "error": "invalid_user_id", "message": "현재 사용자 UUID 가 유효하지 않습니다."}
    if not sub_clean or not _UUID_PATTERN.match(sub_clean):
        return {
            "success": False,
            "needs_clarification": True,
            "missing": ["subscription_id"],
            "message": "거절할 정기배송 ID 를 알려주세요.",
        }

    from app.services.subscription_service import subscription_service
    from uuid import UUID as _UUID

    try:
        _run_async_in_thread(
            lambda: subscription_service.reject_subscription(
                subscription_id=_UUID(sub_clean), user_id=_UUID(user_clean)
            )
        )
    except Exception as e:
        return _service_error_payload(e)

    msg = "정기배송 요청을 거절했습니다."
    if reason:
        msg = f"{msg} (사유: {reason})"
    return {
        "success": True,
        "subscription_id": sub_clean,
        "status": "REJECTED",
        "reason": reason,
        "message": msg,
    }


def create_subscription_from_order(
    user_id: str = "",
    order_id: str = "",
    frequency: str = "",
    start_date: str = "",
    end_date: Optional[str] = None,
) -> dict:
    """기존 주문의 품목을 그대로 정기배송으로 전환 신청한다.

    예: '망고 2kg 주문을 정기배송으로 전환해줘' → 해당 주문의 order_items 를
        그대로 subscription_items 로 복제하고 PENDING 상태로 등록한다.
    상대방이 수락하면 ACTIVE 로 전환된다.
    """
    user_clean = (user_id or "").strip()
    order_clean = (order_id or "").strip()

    if not user_clean or not _UUID_PATTERN.match(user_clean):
        return {"success": False, "error": "invalid_user_id", "message": "현재 사용자 UUID 가 유효하지 않습니다."}
    if not order_clean or not _UUID_PATTERN.match(order_clean):
        return {
            "success": False,
            "needs_clarification": True,
            "missing": ["order_id"],
            "message": "어떤 주문을 정기배송으로 전환할지 알려주세요. (주문 번호 또는 주문 ID)",
        }

    missing: list[str] = []
    freq_norm = _normalize_frequency(frequency)
    if not freq_norm:
        missing.append("frequency")
    start_norm = _normalize_iso_date(start_date)
    if not start_norm:
        missing.append("start_date")

    end_norm = _normalize_iso_date(end_date) if end_date else None
    if end_date and not end_norm:
        return {
            "success": False,
            "needs_clarification": True,
            "missing": ["end_date"],
            "message": "end_date 는 YYYY-MM-DD 형식이어야 합니다.",
        }

    if missing:
        msg_parts: list[str] = []
        if "frequency" in missing:
            msg_parts.append("배송 주기(매주/격주/매월)")
        if "start_date" in missing:
            msg_parts.append("시작 날짜(YYYY-MM-DD)")
        return {
            "success": False,
            "needs_clarification": True,
            "missing": missing,
            "message": "정기배송 전환에 " + " 와 ".join(msg_parts) + " 가 필요합니다.",
        }

    try:
        supabase = get_supabase_client()
        order_result = (
            supabase.table("orders")
            .select("id, buyer_id, seller_id, delivery_address, notes, order_number, status")
            .eq("id", order_clean)
            .is_("deleted_at", None)
            .limit(1)
            .execute()
        )
        if not order_result.data:
            return {"success": False, "error": "order_not_found", "message": "해당 주문을 찾을 수 없습니다."}
        order = order_result.data[0]

        if user_clean not in (order.get("buyer_id"), order.get("seller_id")):
            return {
                "success": False,
                "error": "forbidden",
                "message": "해당 주문의 당사자(구매자/판매자)만 정기배송으로 전환할 수 있습니다.",
            }

        items_result = (
            supabase.table("order_items")
            .select("product_id, quantity, unit_price, products(name, unit)")
            .eq("order_id", order_clean)
            .execute()
        )
        raw_items = items_result.data or []
        if not raw_items:
            return {
                "success": False,
                "error": "no_items",
                "message": "해당 주문에 품목이 없어 정기배송으로 전환할 수 없습니다.",
            }

        sub_items: list[dict] = []
        for it in raw_items:
            product = it.get("products") or {}
            unit_value = product.get("unit") if isinstance(product, dict) else None
            try:
                quantity = int(it.get("quantity"))
                unit_price = int(it.get("unit_price"))
            except (TypeError, ValueError):
                continue
            if not it.get("product_id") or quantity <= 0 or unit_price < 0 or not unit_value:
                continue
            sub_items.append({
                "product_id": it["product_id"],
                "quantity": quantity,
                "unit_price": unit_price,
                "unit": unit_value,
            })

        if not sub_items:
            return {
                "success": False,
                "error": "no_valid_items",
                "message": "해당 주문에서 정기배송으로 변환 가능한 유효 품목을 찾지 못했습니다.",
            }

        payload = {
            "seller_id": order["seller_id"],
            "buyer_id": order["buyer_id"],
            "frequency": freq_norm,
            "start_date": start_norm,
            "end_date": end_norm,
            "delivery_address": order.get("delivery_address"),
            "notes": order.get("notes"),
            "items": sub_items,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

    from app.services.subscription_service import subscription_service
    from uuid import UUID as _UUID

    try:
        sub = _run_async_in_thread(
            lambda: subscription_service.create_subscription(
                user_id=_UUID(user_clean), payload=payload
            )
        )
    except Exception as e:
        return _service_error_payload(e)

    return {
        "success": True,
        "subscription_id": sub.get("id") if isinstance(sub, dict) else None,
        "status": sub.get("status") if isinstance(sub, dict) else "PENDING",
        "source_order_id": order_clean,
        "source_order_number": order.get("order_number"),
        "frequency": freq_norm,
        "start_date": start_norm,
        "end_date": end_norm,
        "items_count": len(sub_items),
        "message": (
            f"주문 {order.get('order_number') or order_clean[:8]} 의 품목을 그대로 정기배송 요청으로 보냈습니다. "
            f"(주기: {freq_norm}, 시작: {start_norm}) 상대방이 수락하면 자동 활성화됩니다."
        ),
    }


# ─────────────────────────────────────────────
# tool 이름 → 함수 매핑 테이블
# ─────────────────────────────────────────────

# 오케스트레이터가 LLM 의 tool_use 응답에서 tool 이름을 보고
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
    "update_order": update_order,
    "create_order": create_order,
    "delete_order": delete_order,
    "find_sellers_by_product": find_sellers_by_product,
    "find_buyers_by_product": find_buyers_by_product,
    "open_chat_room": open_chat_room,
    "get_chat_rooms": get_chat_rooms,
    "get_chat_messages": get_chat_messages,
    "send_chat_message": send_chat_message,
    "get_calendar_events": get_calendar_events,
    "create_calendar_event": create_calendar_event,
    "update_calendar_event": update_calendar_event,
    "delete_calendar_event": delete_calendar_event,
    "find_alternative_partners": find_alternative_partners,
    "get_user_profile": get_user_profile,
    "request_partner_registration": request_partner_registration,
    "request_partner_registration_by_name": request_partner_registration_by_name,
    # 카운터오퍼 / 납품일 변경 — order_service async 메서드를 thread+loop 로 호출
    "submit_counter_offer": submit_counter_offer,
    "accept_counter_offer": accept_counter_offer,
    "reject_counter_offer": reject_counter_offer,
    "submit_delivery_date_change": submit_delivery_date_change,
    "accept_delivery_date_change": accept_delivery_date_change,
    "reject_delivery_date_change": reject_delivery_date_change,
    # 정기배송(Subscription) — subscription_service async 메서드를 thread+loop 로 호출
    "create_subscription_request": create_subscription_request,
    "accept_subscription_request": accept_subscription_request,
    "reject_subscription_request": reject_subscription_request,
    "create_subscription_from_order": create_subscription_from_order,
}
