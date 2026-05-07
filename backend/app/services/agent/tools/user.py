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
        "판매자와 상품을 함께 조회하는 통합 도구. 세 가지 시나리오를 한 번에 처리한다. "
        "(1) 카테고리 검색: 사용자가 '사과 파는 곳', '과일 판매자' 같이 품목/카테고리로 물으면 category 만 전달 → 해당 카테고리의 판매자+상품 목록 반환. "
        "(2) 특정 판매자의 상품 목록 조회: 사용자가 '○○농산이 파는 상품', 'test3 판매자가 뭐 팔아?', '행복농산 상품 보여줘' 같이 특정 판매자의 상품 목록을 물으면 seller_id(UUID 알면) 또는 seller_name_or_company(이름/업체명)를 전달 → 그 판매자 한 곳의 전체 상품 반환. category 는 생략 가능. "
        "(3) 결합 검색: 특정 판매자 + 특정 카테고리/상품명을 동시에 필터링 가능. "
        "category, seller_id, seller_name_or_company 중 최소 1개는 반드시 전달해야 한다. "
        "응답의 seller_id 는 UUID 형식이라 create_order 의 seller_id 에 그대로 사용 가능. "
        "사용자가 직후 발화에서 회사명/담당자만 언급해도 이 응답을 컨텍스트로 활용해 다시 get_user_profile 을 호출할 필요 없이 매칭되는 항목의 seller_id 를 그대로 쓸 것."
    ),
    parameters={
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "조회할 상위 카테고리명 (선택). 허용값: FRUIT, VEGETABLE, GRAIN, MUSHROOM, SEAFOOD, MEAT, DAIRY, HERB, LEGUME, ROOT, LEAF, PROCESSED, OTHER. 사용자가 카테고리 단위로 묻는 경우(예: '과일 판매자', '곡물 보여줘')에만 채운다. 사용자가 특정 상품명만 언급한 경우(예: '감자 찾아줘')에는 product_name 만 사용하고 이 필드는 비워둘 것 — 카테고리를 임의 추론하면 다른 카테고리에 등록된 동명 상품이 누락된다(예: 같은 '감자' 가 한 곳은 VEGETABLE, 다른 곳은 GRAIN 으로 등록될 수 있음). 전체 카테고리를 보려면 'ALL' 또는 생략. seller_id/seller_name_or_company 를 지정해 특정 판매자 상품만 보려면 이 필드는 비워두는 것이 자연스럽다.",
            },
            "product_name": {
                "type": "string",
                "description": "검색할 상품명 (선택). 예: 당근, 사과. 특정 상품을 찾을 때 입력하면 정확한 결과를 반환한다.",
            },
            "seller_id": {
                "type": "string",
                "description": "특정 판매자의 UUID (선택). 직전 대화에서 받은 seller_id 가 있거나 get_user_profile 응답으로 얻은 UUID 가 있으면 이 값을 전달한다. 이 필드를 채우면 그 판매자 한 곳의 상품만 반환한다.",
            },
            "seller_name_or_company": {
                "type": "string",
                "description": "판매자 이름 또는 회사명 (선택, 부분 일치 검색). 사용자가 '○○농산이 파는 상품'처럼 UUID 없이 이름/업체명만 말한 경우 이 필드를 사용. 내부적으로 users.name 또는 users.company_name 에 ILIKE 매칭한다. 매칭이 여러 명이면 모두 합쳐 반환한다(LLM 이 응답에서 사용자가 의도한 후보를 골라야 함).",
            },
        },
        "required": [],
    },
    groups=("inventory_order",),
)
def find_sellers_by_product(
    category: Optional[str] = None,
    product_name: Optional[str] = None,
    seller_id: Optional[str] = None,
    seller_name_or_company: Optional[str] = None,
) -> dict:
    """users 테이블 기준으로 판매자를 조회하고, products 테이블을 부가적으로 조인한다.

    필터 우선순위:
      1) seller_id (UUID) 가 있으면 그 한 명만.
      2) seller_name_or_company 가 있으면 name/company_name ILIKE 매칭으로 후보 판매자(들).
      3) 둘 다 없으면 전체 SELLER role 사용자.
    그 위에 category, product_name 으로 상품 필터를 추가 적용한다.

    최소 1개 필터(category / seller_id / seller_name_or_company / product_name) 가 필요.
    아무 조건도 없으면 너무 광범위한 조회가 되므로 거부.
    """
    from collections import defaultdict

    # 모두 비어있으면 거부
    if not any([category, seller_id, seller_name_or_company, product_name]):
        return {
            "success": False,
            "error": "missing_filter",
            "detail": "category, seller_id, seller_name_or_company, product_name 중 최소 1개를 전달해야 합니다.",
            "sellers": [],
            "seller_count": 0,
        }

    # 단일 판매자 조회 모드 여부
    is_single_seller_query = bool(seller_id) or bool(seller_name_or_company)

    try:
        supabase = get_supabase_client()

        # 1단계: 판매자 후보 결정
        sellers_query = (
            supabase.table("users")
            .select("id, name, company_name, phone")
            .eq("role", "SELLER")
            .eq("is_active", True)
            .is_("deleted_at", None)
        )

        if seller_id:
            sellers_query = sellers_query.eq("id", seller_id)
        elif seller_name_or_company:
            q = seller_name_or_company.strip()
            sellers_query = sellers_query.or_(
                f"name.ilike.%{q}%,company_name.ilike.%{q}%"
            )

        sellers_result = sellers_query.execute()
        all_sellers = sellers_result.data or []

        if not all_sellers:
            # 판매자 후보가 0건인 경우 — single_seller 모드면 더 명확한 메시지
            if is_single_seller_query:
                return {
                    "success": True,
                    "seller_count": 0,
                    "sellers": [],
                    "_response_guide": (
                        "지정한 판매자(이름/업체명/UUID) 와 매칭되는 활성 SELLER 가 없습니다. "
                        "사용자에게 '○○ 라는 판매자를 찾을 수 없어요. 정확한 이름이나 업체명을 알려주세요'라고 자연체로 안내하세요. "
                        "다른 판매자나 상품을 임의로 추천하지 마세요."
                    ),
                }
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
            .is_("deleted_at", None)
        )

        # 단일 판매자 조회는 재고 0 도 포함해 "어떤 상품 라인업이 있는지" 보여준다.
        # 카테고리 검색은 기존 동작 유지(재고 있는 상품만).
        if not is_single_seller_query:
            products_query = products_query.gt("stock_quantity", 0)

        if category and category.upper() != "ALL":
            products_query = products_query.eq("category", category.upper())

        if product_name:
            products_query = products_query.ilike("name", f"%{product_name}%")

        products_result = products_query.execute()
        products = products_result.data or []

        # ────────────────────────────────────────────
        # robust 화 (2026-05-06): product_name 이 명시되면 카테고리 over-narrowing 방어
        #
        # 배경: LLM 이 "감자 찾아줘" 같은 발화에 대해 product_name='감자' + category='VEGETABLE'
        # 식으로 둘 다 채워 넘기는 경우가 있다. 이 때 같은 이름의 상품이 다른 카테고리(GRAIN 등)
        # 로 등록되어 있으면 1차 결과에서 누락된다. 기존 fallback 은 `not products` 일 때만
        # 발동해 1차에 한 건이라도 잡히면 다른 카테고리 동명 상품이 영원히 누락됐다.
        #
        # 새 정책: product_name 이 있고 category 도 같이 좁혀진 경우, 카테고리 무관 ILIKE 결과를
        # 추가로 가져와 union 한다. (seller_id, name) 키로 중복 제거.
        # 단일 판매자 조회는 그 판매자만 봐야 하므로 그대로 유지.
        # ────────────────────────────────────────────
        if (
            product_name
            and category
            and category.upper() != "ALL"
            and not is_single_seller_query
        ):
            extra_query = (
                supabase.table("products")
                .select("seller_id, name, price_per_unit, stock_quantity, unit, origin, spec, status, category")
                .in_("seller_id", seller_ids)
                .gt("stock_quantity", 0)
                .is_("deleted_at", None)
                .ilike("name", f"%{product_name}%")
            )
            extra_result = extra_query.execute()
            extra = extra_result.data or []
            seen = {(p.get("seller_id"), p.get("name")) for p in products}
            for p in extra:
                key = (p.get("seller_id"), p.get("name"))
                if key not in seen:
                    products.append(p)
                    seen.add(key)

        # category 필터 결과가 없으면 ALL로 재시도 (단일 판매자 모드에는 적용하지 않음 —
        # 그 판매자가 그 카테고리를 안 다루는 게 명확한 정보이므로 fallback 하지 않는다)
        if (
            not products
            and category
            and category.upper() != "ALL"
            and not is_single_seller_query
        ):
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
            # 단일 판매자 모드: 상품 0건이어도 판매자 정보 자체는 응답에 포함
            # (LLM 이 "상품이 등록되지 않았습니다"라고 정확히 답할 수 있게)
            if not seller_products and not is_single_seller_query:
                continue
            seller_info = seller_map[sid]
            sellers_with_products.append({
                "seller_id": sid,
                "seller_name": seller_info.get("name", "알 수 없음"),
                "seller_company": seller_info.get("company_name", ""),
                "seller_phone": seller_info.get("phone", ""),
                "products": seller_products,
            })

        # 응답 가이드는 모드에 따라 분기
        if is_single_seller_query:
            if not sellers_with_products or all(
                len(s["products"]) == 0 for s in sellers_with_products
            ):
                response_guide = (
                    "지정 판매자가 등록한 상품이 없습니다. "
                    "사용자에게 '○○ 판매자가 현재 등록한 상품이 없습니다'라고 자연체로 정확히 안내하세요. "
                    "다른 판매자나 상품을 임의로 추천하지 마세요."
                )
            elif len(sellers_with_products) == 1:
                response_guide = (
                    "단일 판매자의 상품 라인업입니다. "
                    "첫 문장에 '○○(회사명) 판매자가 판매 중인 상품 N건입니다.' 형식으로 안내하고, "
                    "products 배열의 상품을 1. 2. 3. 번호로 모두 나열하세요(많아도 최대 15개까지). "
                    "각 상품은 '품명 — 가격(원/단위), 재고 수량(단위), 원산지(있으면), 상태' 순으로 자연체 한국어로 풀어 쓰세요. "
                    "상태가 OUT_OF_STOCK 이면 '품절'로, LOW_STOCK 이면 '재고 부족'으로 한글 표기. "
                    "표/별표/헤더 사용 금지. 16개 이상이면 '외 N개 상품이 더 있습니다'로 요약."
                )
            else:
                response_guide = (
                    "이름/업체명 검색이 여러 판매자에 매칭됐습니다. "
                    "첫 문장에 '○○ 와 매칭되는 판매자가 N명입니다.' 형식으로 안내하고, "
                    "각 판매자별로 회사명/담당자를 명시한 뒤 그 판매자의 상품을 1. 2. 3. 으로 나열하세요. "
                    "사용자에게 '어느 판매자의 상품을 보고 싶으신가요?'라고 마지막에 자연스럽게 묻기. "
                    "표/별표/헤더 사용 금지."
                )
        else:
            response_guide = (
                "seller_count가 실제 판매자 수입니다. 첫 문장에 전체 판매자 수(seller_count)를 안내하세요. "
                "반드시 상위 5개 판매자를 1. 2. 3. 4. 5. 번호를 붙여 표시하세요. 판매자가 5개 미만이면 전체를 번호와 함께 표시하세요. "
                "각 판매자 아래에 products 배열의 상품들을 들여쓰기로 나열하세요. "
                "나머지 판매자는 '외 N개 판매처가 더 있습니다'로 요약하세요. "
                "상품별로 가격, 재고, 원산지(있으면)를 간결하게 표시하세요."
            )

        return {
            "success": True,
            "seller_count": len(sellers_with_products),
            "sellers": sellers_with_products,
            "query_mode": "single_seller" if is_single_seller_query else "category_search",
            "_response_guide": response_guide,
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
