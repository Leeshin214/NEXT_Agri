"""상품/재고 관련 도구.

원본: backend/app/services/agent_tools.py 의 product 섹션 (단계 1: 본문 그대로 복사 + @tool 데코레이터 추가).
agent_tools.py 의 함수는 단계 2 에서 shim 으로 변환된다.

도메인 helper:
- _find_product_by_name : 이름 기반 상품 검색 (fuzzy fallback). order/subscription 모듈에서도 lazy import.

Cross-domain helper:
- _UUID_PATTERN : agent_tools.py 에 정의 (단계 2 에서 _shared.py 로 이동 예정).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.core.supabase import get_supabase_client

from .._registry import tool


# ─────────────────────────────────────────────
# 헬퍼: 이름 기반 상품 검색 (fuzzy fallback 포함)
# (order/subscription 모듈에서 lazy import 로 재사용)
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

@tool(
    name="get_products",
    description=(
        "판매자의 상품 및 재고 목록을 조회한다. "
        "전체 상품을 보거나 특정 카테고리(예: 과일, 채소)만 필터링할 수 있다."
    ),
    parameters={
        "type": "object",
        "properties": {
            "seller_id": {
                "type": "string",
                "description": "판매자의 UUID (현재 로그인한 판매자 ID)",
            },
            "category": {
                "type": "string",
                "description": "필터링할 카테고리명 (선택). 없으면 전체 조회. 허용값: FRUIT, VEGETABLE, GRAIN, MUSHROOM, SEAFOOD, MEAT, DAIRY, HERB, LEGUME, ROOT, LEAF, PROCESSED, OTHER. 사용자가 어떤 표현을 써도 가장 가까운 카테고리로 자동 변환할 것.",
            },
        },
        "required": ["seller_id"],
    },
    groups=("inventory_order",),
)
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


@tool(
    name="check_stock",
    description=(
        "특정 상품 ID로 재고 수량, 단위, 상태(NORMAL/LOW_STOCK/OUT_OF_STOCK)를 확인한다."
    ),
    parameters={
        "type": "object",
        "properties": {
            "product_id": {
                "type": "string",
                "description": "조회할 상품의 UUID",
            },
            "seller_id": {
                "type": "string",
                "description": "판매자 UUID. product_name으로 검색할 때 범위를 좁히기 위해 사용",
            },
            "product_name": {
                "type": "string",
                "description": "조회할 상품명. product_id 모를 때 사용",
            },
        },
        "required": ["product_id"],
    },
    groups=("inventory_order",),
)
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


@tool(
    name="update_stock",
    description=(
        "특정 상품의 재고 수량을 새 값으로 업데이트한다. "
        "수량에 따라 상태(NORMAL/LOW_STOCK/OUT_OF_STOCK)가 자동으로 변경된다."
    ),
    parameters={
        "type": "object",
        "properties": {
            "product_id": {
                "type": "string",
                "description": "재고를 수정할 상품의 UUID",
            },
            "new_quantity": {
                "type": "string",
                "description": "변경할 재고 수량 (0 이상의 정수)",
            },
            "seller_id": {
                "type": "string",
                "description": "판매자 UUID. product_name으로 검색할 때 범위를 좁히기 위해 사용",
            },
            "product_name": {
                "type": "string",
                "description": "재고를 수정할 상품명. product_id 모를 때 사용",
            },
        },
        "required": ["new_quantity"],
    },
    groups=("inventory_order",),
    int_fields=frozenset({"new_quantity"}),
)
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


@tool(
    name="create_product",
    description=(
        "새 상품을 등록한다. "
        "상품명, 카테고리, 단가, 재고수량, 단위는 필수. "
        "산지, 규격, 최소주문수량, 설명은 선택사항."
    ),
    parameters={
        "type": "object",
        "properties": {
            "seller_id": {
                "type": "string",
                "description": "판매자의 UUID (현재 로그인한 판매자 ID)",
            },
            "name": {
                "type": "string",
                "description": "상품명 (예: 사과, 배추, 토마토)",
            },
            "category": {
                "type": "string",
                "description": "허용값: FRUIT, VEGETABLE, GRAIN, MUSHROOM, SEAFOOD, MEAT, DAIRY, HERB, LEGUME, ROOT, LEAF, PROCESSED, OTHER. 사용자가 어떤 표현을 써도 가장 가까운 카테고리로 자동 변환할 것.",
            },
            "price_per_unit": {
                "type": "string",
                "description": "단위당 가격 (원)",
            },
            "stock_quantity": {
                "type": "string",
                "description": "초기 재고 수량",
            },
            "unit": {
                "type": "string",
                "description": "판매 단위 (예: kg, box, piece, bag, 개, 포대, 묶음, g, L, ml, 판, 줄, 세트)",
            },
            "origin": {
                "type": "string",
                "description": "산지/원산지 (선택, 예: 나주, 제주)",
            },
            "spec": {
                "type": "string",
                "description": "규격/등급 (선택, 예: 특, 상, 중)",
            },
            "min_order_qty": {
                "type": "string",
                "description": "최소 주문 수량 (선택)",
            },
            "description": {
                "type": "string",
                "description": "상품 상세 설명 (선택)",
            },
        },
        "required": ["seller_id", "name", "category", "price_per_unit", "stock_quantity", "unit"],
    },
    groups=("inventory_order",),
    int_fields=frozenset({"price_per_unit", "stock_quantity", "min_order_qty"}),
)
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


@tool(
    name="delete_product",
    description=(
        "상품을 삭제한다(soft delete). deleted_at을 현재 시간으로 설정하며, "
        "실제 데이터는 보존된다. seller_id가 일치해야만 삭제 가능하다."
    ),
    parameters={
        "type": "object",
        "properties": {
            "product_id": {
                "type": "string",
                "description": "삭제할 상품의 UUID. 모르면 빈 문자열로 전달.",
            },
            "seller_id": {
                "type": "string",
                "description": "요청하는 판매자의 UUID (현재 로그인한 판매자 ID)",
            },
            "name": {
                "type": "string",
                "description": "삭제할 상품명. product_id를 모를 때 이름으로 검색.",
            },
        },
        "required": ["seller_id"],
    },
    groups=("inventory_order",),
)
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


@tool(
    name="update_product",
    description=(
        "상품 정보를 수정한다. 전달된 필드만 업데이트된다. "
        "seller_id가 일치해야만 수정 가능하다. "
        "수정 가능 필드: name, price_per_unit, category, origin, spec, description. "
        "중요: product_id를 몰라도 product_name에 상품명을 넣으면 agent_tools.update_product가 해당 판매자의 상품을 이름으로 찾아 수정한다. "
        "따라서 '감자 단가 2700원으로 바꿔줘'처럼 상품명과 변경값이 있으면 확인 질문 없이 즉시 update_product를 호출하라."
    ),
    parameters={
        "type": "object",
        "properties": {
            "product_id": {
                "type": "string",
                "description": "수정할 상품의 UUID. 모르면 빈 문자열로 전달하고 product_name을 반드시 사용한다.",
            },
            "seller_id": {
                "type": "string",
                "description": "요청하는 판매자의 UUID (현재 로그인한 판매자 ID)",
            },
            "product_name": {
                "type": "string",
                "description": "수정할 상품명. product_id를 모를 때 반드시 사용한다. 예: 감자, 옥수수",
            },
            "name": {
                "type": "string",
                "description": "변경할 상품명 (선택, 이름 자체를 바꿀 때 사용)",
            },
            "price_per_unit": {
                "type": "string",
                "description": "변경할 단위당 가격 (원, 선택)",
            },
            "category": {
                "type": "string",
                "description": "변경할 카테고리 (선택). 허용값: FRUIT, VEGETABLE, GRAIN, MUSHROOM, SEAFOOD, MEAT, DAIRY, HERB, LEGUME, ROOT, LEAF, PROCESSED, OTHER. 사용자가 어떤 표현을 써도 가장 가까운 카테고리로 자동 변환할 것.",
            },
            "origin": {
                "type": "string",
                "description": "변경할 산지/원산지 (선택)",
            },
            "spec": {
                "type": "string",
                "description": "변경할 규격/등급 (선택)",
            },
            "description": {
                "type": "string",
                "description": "변경할 상품 설명 (선택)",
            },
        },
        "required": ["seller_id"],
    },
    groups=("inventory_order",),
    int_fields=frozenset({"price_per_unit"}),
)
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
