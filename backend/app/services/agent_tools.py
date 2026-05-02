"""
agent_tools.py — LangGraph 오케스트레이터에서 실제로 호출되는 도구 함수들

각 함수는 Supabase DB를 직접 조회/수정하고, 결과를 dict로 반환한다.
오케스트레이터(orchestrator.py)가 LLM의 tool 선택에 따라 TOOL_FUNCTION_MAP을 통해 실행한다.
현재 LLM: OpenAI (gpt-4o-mini)
"""

import asyncio
import json
import random
from calendar import monthrange
from datetime import datetime, timezone
from typing import Optional

from app.core.supabase import get_supabase_client


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
            for item in items:
                product = item.get("products") if isinstance(item, dict) else None
                if not product:
                    continue
                name = product.get("name")
                if name:
                    product_names.append(name)

            if not product_names:
                row["product_summary"] = None
            elif len(product_names) == 1:
                row["product_summary"] = product_names[0]
            else:
                row["product_summary"] = f"{product_names[0]} 외 {len(product_names) - 1}건"

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
        _sync_calendar_events_for_order_id(order_id)

        return {
            "success": True,
            "order_id": order_id,
            "new_status": new_status,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


_UUID_PATTERN = __import__('re').compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    __import__('re').IGNORECASE,
)


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
    delivery_date: Optional[str] = None,
    delivery_address: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    """새 주문을 생성한다.

    order_number UNIQUE 충돌 (PostgreSQL 23505) 발생 시 최대 3회 재시도.
    동시 합의 자동 주문 (chat_ws._handle_consensus) 흐름에서 동일 초 + 동일 random 4자리 시 발생 가능.
    product_id가 UUID가 아닌 상품명으로 들어온 경우 자동으로 이름 검색해 UUID로 변환한다.
    """
    # 지연 import — 모듈 임포트 시점 의존성 회피
    from postgrest.exceptions import APIError as PostgrestAPIError

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
                correct = _find_product_by_name(supabase, "", seller_id)
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

        subtotal = quantity * unit_price
        total_amount = subtotal

        today = datetime.now(timezone.utc).strftime("%Y%m%d")

        # order_number UNIQUE 충돌 시 최대 3회 재생성 + 재시도
        order_result = None
        last_err: Optional[Exception] = None
        for attempt in range(3):
            order_number = f"ORD-{today}-{random.randint(1000, 9999)}"
            try:
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
                break
            except PostgrestAPIError as e:
                err_code = getattr(e, "code", "") or ""
                err_msg = (getattr(e, "message", "") or "") + " " + str(e)
                if err_code == "23505" or "23505" in err_msg or "duplicate" in err_msg.lower():
                    last_err = e
                    continue
                raise
        if order_result is None or not order_result.data:
            return {
                "success": False,
                "error": f"주문 번호 생성에 반복 실패했습니다. {last_err}" if last_err else "주문 생성에 실패했습니다.",
            }

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
        _sync_calendar_events_for_order_id(order_id)

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

    chat_rooms 테이블에서 seller_id/buyer_id 조합으로 검색하며,
    두 사용자 중 누가 판매자·구매자인지 알 수 없으므로 역할 기반으로 결정한다.
    기존 방이 항상 검색되므로 동일 (seller, buyer) 페어는 1개만 존재할 수밖에 없는 구조 →
    rate-limit throttle 은 dead code 였으므로 제거.
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

        # 기존 방 검색
        existing = (
            supabase.table("chat_rooms")
            .select("id")
            .eq("seller_id", seller_id)
            .eq("buyer_id", buyer_id)
            .execute()
        )
        if existing.data:
            room_id = existing.data[0]["id"]
            # order_id가 주어졌으면 기존 방에도 업데이트
            if order_id:
                supabase.table("chat_rooms").update({"order_id": order_id}).eq("id", room_id).execute()
            return {
                "success": True,
                "room_id": room_id,
                "is_new": False,
                "partner_name": partner_name,
            }

        # C-5: 24h rate-limit throttle 제거 — 기존 방이 항상 검색되므로 동일 페어는 1개만
        # 존재할 수밖에 없어 dead code 였음.

        # 새 채팅방 생성
        insert_payload: dict = {"seller_id": seller_id, "buyer_id": buyer_id}
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
                "id, last_message, created_at, "
                "buyer:users!buyer_id(name, company_name), "
                "seller:users!seller_id(name, company_name)"
            )
            .or_(f"buyer_id.eq.{user_id},seller_id.eq.{user_id}")
            .order("created_at", desc=True)
            .execute()
        )
        
        rooms = result.data or []
        flattened = []
        
        for r in rooms:
            buyer = r.get("buyer") or {}
            seller = r.get("seller") or {}
            
            flattened.append({
                "room_id": r["id"],
                "last_message": r.get("last_message"),
                "created_at": r["created_at"],
                "buyer_name": buyer.get("name"),
                "buyer_company": buyer.get("company_name"),
                "seller_name": seller.get("name"),
                "seller_company": seller.get("company_name"),
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

def send_chat_message(room_id: str, sender_id: str, content: str) -> dict:
    """채팅방에 새 메시지를 전송한다."""
    try:
        supabase = get_supabase_client()
        
        # 1) 메시지 저장
        msg_result = (
            supabase.table("messages")
            .insert({"room_id": room_id, "sender_id": sender_id, "content": content})
            .execute()
        )
        
        # 2) 채팅방의 'last_message' 업데이트 (목록에서 바로 보이게)
        supabase.table("chat_rooms").update({"last_message": content}).eq("id", room_id).execute()
        
        return {
            "success": True,
            "message": "메시지가 전송되었습니다.",
            "sent_at": msg_result.data[0]["created_at"] if msg_result.data else None
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

# ─────────────────────────────────────────────
# 캘린더 도구
# ─────────────────────────────────────────────

import re

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
        check = supabase.table("calendar_events").select("id, user_id, title").eq("id", event_id).is_("deleted_at", None).execute()
        if not check.data:
            return {"success": False, "error": "해당 일정을 찾을 수 없습니다."}
        if check.data[0]["user_id"] != user_id:
            return {"success": False, "error": "권한 없음: 본인의 일정만 수정할 수 있습니다."}

        update_data: dict = {}
        if title is not None: update_data["title"] = title
        if event_date is not None: update_data["event_date"] = event_date
        if event_type is not None: update_data["event_type"] = event_type
        if description is not None: update_data["description"] = description

        if not update_data:
            return {"success": False, "error": "수정할 내용이 없습니다."}

        supabase.table("calendar_events").update(update_data).eq("id", event_id).execute()
        return {"success": True, "event_id": event_id, "message": f"일정 '{check.data[0]['title']}'이(가) 수정되었습니다."}
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
}
