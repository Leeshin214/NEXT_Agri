"""사용자 / 판매자·구매자 탐색 / 채팅방 개설 도구.

도구 4 종:
- get_user_profile         : 사용자 프로필 조회 (id/이름/회사명)
- find_sellers_by_product  : 카테고리별 판매자 + 상품 목록
- find_buyers_by_product   : 카테고리별 구매 이력 보유 바이어 목록
- open_chat_room           : 두 사용자 간 채팅방 조회/생성

Cross-domain 의존 (agent/_shared.py 에서 lazy import):
- _UUID_PATTERN
"""
from __future__ import annotations

from typing import Optional

from app.core.supabase import get_supabase_client

from .._registry import tool


@tool(
    name="get_user_profile",
    description=(
        "사용자 프로필을 조회한다. "
        "user_id, username(name), company_name 중 하나 이상으로 검색 가능하다. "
        "채팅 상대 확인이나 거래처 정보 확인 시 활용한다."
    ),
    parameters={
        "type": "object",
        "properties": {
            "user_id": {
                "type": "string",
                "description": "조회할 사용자의 UUID (선택)",
            },
            "username": {
                "type": "string",
                "description": "조회할 사용자 이름 (선택, 부분 일치 검색)",
            },
            "company_name": {
                "type": "string",
                "description": "조회할 회사명 (선택, 부분 일치 검색)",
            },
        },
        "required": [],
    },
    groups=("inventory_order",),
)
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

        # 1순위: username(name 컬럼) 검색 — 이름으로 찾을 때 user_id보다 우선
        if username:
            result = (
                supabase.table("users")
                .select(COLUMNS)
                .ilike("name", f"%{username}%")
                .eq("is_active", True)
                .is_("deleted_at", None)
                .limit(5)
                .execute()
            )
            if result.data:
                return {"success": True, "user": result.data[0]}

        # 2순위: company_name 검색
        if company_name:
            result = (
                supabase.table("users")
                .select(COLUMNS)
                .ilike("company_name", f"%{company_name}%")
                .eq("is_active", True)
                .is_("deleted_at", None)
                .limit(5)
                .execute()
            )
            if result.data:
                return {"success": True, "user": result.data[0]}

        # 3순위: username/company_name 모두 없을 때만 user_id로 직접 조회
        if user_id and not username and not company_name:
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

        return {"success": False, "error": "user_not_found"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool(
    name="find_sellers_by_product",
    description=(
        "특정 카테고리의 모든 판매자 및 상품 목록을 조회한다. "
        "구매자가 특정 품목(예: 풋사과, 청사과)을 찾을 때, 이 도구로 상위 카테고리(예: FRUIT) 전체를 조회한 후 "
        "LLM이 직접 결과값을 읽고 사용자가 원하는 세부 품목 조건에 맞는 것만 필터링해서 답변해야 한다. "
        "정확한 상품명을 알고 있는 경우 product_name을 함께 전달하면 더 정확한 결과를 반환한다. "
        "응답의 seller_id 는 UUID 형식이라 create_order 의 seller_id 에 그대로 사용 가능. 사용자가 직후 발화에서 회사명/담당자만 언급해도 이 응답을 컨텍스트로 활용해 다시 get_user_profile 을 호출할 필요 없이 매칭되는 항목의 seller_id 를 그대로 쓸 것."
    ),
    parameters={
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "조회할 상위 카테고리명. 허용값: FRUIT, VEGETABLE, GRAIN, MUSHROOM, SEAFOOD, MEAT, DAIRY, HERB, LEGUME, ROOT, LEAF, PROCESSED, OTHER. 사용자가 어떤 표현을 써도 가장 가까운 카테고리로 자동 변환할 것. 카테고리가 모호하거나 전체를 뒤져야 하면 'ALL'을 입력하세요.",
            },
            "product_name": {
                "type": "string",
                "description": "검색할 상품명 (선택). 예: 당근, 사과. 특정 상품을 찾을 때 입력하면 정확한 결과를 반환한다.",
            },
        },
        "required": ["category"],
    },
    groups=("inventory_order",),
)
def find_sellers_by_product(category: str, product_name: Optional[str] = None) -> dict:
    """users 테이블 기준으로 판매자를 조회하고, products 테이블을 부가적으로 조인한다."""
    try:
        supabase = get_supabase_client()

        # 1단계: users 테이블에서 SELLER 전체 조회
        sellers_result = (
            supabase.table("users")
            .select("id, name, company_name, phone")
            .eq("role", "SELLER")
            .eq("is_active", True)
            .is_("deleted_at", None)
            .execute()
        )
        all_sellers = sellers_result.data or []

        if not all_sellers:
            return {
                "success": True,
                "seller_count": 0,
                "sellers": [],
            }

        seller_ids = [s["id"] for s in all_sellers]
        seller_map = {s["id"]: s for s in all_sellers}

        # 2단계: products 테이블에서 해당 판매자들의 상품 조회
        products_query = (
            supabase.table("products")
            .select("seller_id, name, price_per_unit, stock_quantity, unit, origin, spec, status, category")
            .in_("seller_id", seller_ids)
            .gt("stock_quantity", 0)
            .is_("deleted_at", None)
        )

        if category and category.upper() != "ALL":
            products_query = products_query.eq("category", category.upper())

        if product_name:
            products_query = products_query.ilike("name", f"%{product_name}%")

        products_result = products_query.execute()
        products = products_result.data or []

        # category 필터 결과가 없으면 ALL로 재시도
        if not products and category and category.upper() != "ALL":
            fallback_query = (
                supabase.table("products")
                .select("seller_id, name, price_per_unit, stock_quantity, unit, origin, spec, status, category")
                .in_("seller_id", seller_ids)
                .gt("stock_quantity", 0)
                .is_("deleted_at", None)
            )
            if product_name:
                fallback_query = fallback_query.ilike("name", f"%{product_name}%")
            products_result = fallback_query.execute()
            products = products_result.data or []

        # 3단계: 판매자별로 상품 그룹화
        from collections import defaultdict
        products_by_seller: dict = defaultdict(list)
        for p in products:
            sid = p.get("seller_id")
            if sid:
                products_by_seller[sid].append({
                    "name": p.get("name"),
                    "price_per_unit": p.get("price_per_unit"),
                    "stock_quantity": p.get("stock_quantity"),
                    "unit": p.get("unit"),
                    "origin": p.get("origin"),
                    "spec": p.get("spec"),
                    "status": p.get("status"),
                    "category": p.get("category"),
                })

        sellers_with_products = []
        for sid in seller_ids:
            seller_products = products_by_seller.get(sid, [])
            if not seller_products:
                continue
            seller_info = seller_map[sid]
            sellers_with_products.append({
                "seller_id": sid,
                "seller_name": seller_info.get("name", "알 수 없음"),
                "seller_company": seller_info.get("company_name", ""),
                "seller_phone": seller_info.get("phone", ""),
                "products": seller_products,
            })

        return {
            "success": True,
            "seller_count": len(sellers_with_products),
            "sellers": sellers_with_products,
            "_response_guide": (
                "seller_count가 실제 판매자 수입니다. 첫 문장에 전체 판매자 수(seller_count)를 안내하세요. "
                "반드시 상위 5개 판매자를 1. 2. 3. 4. 5. 번호를 붙여 표시하세요. 판매자가 5개 미만이면 전체를 번호와 함께 표시하세요. "
                "각 판매자 아래에 products 배열의 상품들을 들여쓰기로 나열하세요. "
                "나머지 판매자는 '외 N개 판매처가 더 있습니다'로 요약하세요. "
                "상품별로 가격, 재고, 원산지(있으면)를 간결하게 표시하세요."
            ),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "sellers": [], "seller_count": 0}


@tool(
    name="find_buyers_by_product",
    description=(
        "특정 카테고리의 상품을 구매한 이력이 있는 바이어 전체 목록을 조회한다. "
        "조회 후 LLM이 직접 결과값을 분석하여 판매자의 특정 품목(예: 풋사과)에 관심 있을 만한 바이어를 필터링한다."
    ),
    parameters={
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "조회할 상위 카테고리명. 허용값: FRUIT, VEGETABLE, GRAIN, MUSHROOM, SEAFOOD, MEAT, DAIRY, HERB, LEGUME, ROOT, LEAF, PROCESSED, OTHER. 사용자가 어떤 표현을 써도 가장 가까운 카테고리로 자동 변환할 것. 모호하면 'ALL'을 입력하세요.",
            },
        },
        "required": ["category"],
    },
    groups=("inventory_order",),
)
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

        return {
            "success": True,
            "buyers": buyers,
            "count": len(buyers),
            "_response_guide": (
                "반드시 상위 5개 구매자를 1. 2. 3. 4. 5. 번호를 붙여 표시하세요. 구매자가 5개 미만이면 전체를 번호와 함께 표시하세요. "
                "나머지는 '외 N명이 더 있습니다'로 요약하세요. "
                "전체 구매자 수는 첫 문장에 안내하세요. "
                "각 구매자의 거래 건수와 총 구매량을 간결하게 표시하세요."
            ),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "buyers": [], "count": 0}


@tool(
    name="open_chat_room",
    description=(
        "사용자의 요청에 따라 판매자와의 1:1 채팅방을 생성합니다. "
        "직전 create_order 결과가 있거나 사용자가 '이 주문 건', '방금 주문', '방금 견적'이라고 말한 경우에는 "
        "반드시 order_id를 함께 전달해야 합니다. "
        "order_id 없이 호출하면 일반 채팅방이 열리므로, 주문/견적 맥락에서는 order_id 없는 호출을 금지합니다. "
        "상대방의 partner_user_id를 모를 경우, 반드시 get_user_profile 도구를 먼저 호출하여 "
        "업체명(company_name)으로 ID를 조회한 뒤 이 도구를 연달아 호출하세요."
    ),
    parameters={
        "type": "object",
        "properties": {
            "user_id": {
                "type": "string",
                "description": "현재 로그인한 사용자의 UUID (state에서 가져옴)",
            },
            "partner_user_id": {
                "type": "string",
                "description": "채팅 상대방의 UUID",
            },
            "order_id": {
                "type": "string",
                "description": "이 채팅방과 연결할 주문 UUID. create_order 직후 호출할 때 반환된 order_id를 넣으세요. 없으면 생략.",
            },
        },
        "required": ["user_id", "partner_user_id"],
    },
    groups=("inventory_order",),
)
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
    from .._shared import _UUID_PATTERN

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
                "_response_guide": f"'{partner_name}'과의 기존 채팅방으로 연결됐습니다. 사용자에게 '왼쪽 채팅 탭에서 확인하세요'라고 안내하세요. 다른 말 붙이지 마세요.",
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
            "_response_guide": f"'{partner_name}'과의 채팅방이 새로 생성됐습니다. 사용자에게 '왼쪽 채팅 탭에서 확인하세요'라고 안내하세요. 다른 말 붙이지 마세요.",
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
