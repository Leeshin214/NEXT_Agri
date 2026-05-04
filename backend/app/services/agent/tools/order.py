"""주문 관련 도구.

원본: backend/app/services/agent_tools.py 의 order 섹션 (단계 1: 본문 그대로 복사 + @tool 데코레이터 추가).
agent_tools.py 의 함수는 단계 2 에서 shim 으로 변환된다.

Cross-domain 의존:
- _UUID_PATTERN, _run_async_in_thread, _service_error_payload, _find_seller_by_name,
  _sync_calendar_events_for_order_id : agent_tools.py 의 cross-domain helper.
  단계 1 에서는 lazy import (단계 2 에서 _shared.py 로 이동 예정).
- _find_product_by_name : product.py 의 도메인 helper.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.core.supabase import get_supabase_client

from .._registry import tool


# ─────────────────────────────────────────────
# 주문 관련 도구
# ─────────────────────────────────────────────

@tool(
    name="get_orders",
    description=(
        "사용자의 주문 목록을 조회한다 (삭제된 주문은 제외 — soft delete 자동 필터). "
        "판매자는 받은 주문, 구매자는 넣은 주문이 조회된다. "
        "단일 상태 필터는 status, 다중 상태 필터는 status_in 을 사용한다 (status_in 이 우선). "
        "사용자가 '진행 중인 주문', '활성 주문', '내 주문' 처럼 진행 상태 전체를 물어보면 "
        "반드시 status_in=['QUOTE_REQUESTED','NEGOTIATING','CONFIRMED','PREPARING','SHIPPING'] "
        "로 호출하라 — 완료(COMPLETED)/취소(CANCELLED) 는 자동 제외된다. "
        "단일 상태(예: '배송 중인 주문', '견적 요청만') 만 묻는 경우엔 status='SHIPPING' 처럼 단일 값 사용. "
        "주의: 사용자가 '거래요청 들어온거 있어?', '새로운 거래' 등을 물어보면 "
        "이것은 새로운 주문/견적 요청을 의미하므로 반드시 이 도구를 호출하여 확인하라."
    ),
    parameters={
        "type": "object",
        "properties": {
            "user_id": {
                "type": "string",
                "description": "조회할 사용자의 UUID",
            },
            "role": {
                "type": "string",
                "description": "사용자 역할: SELLER 또는 BUYER",
                "enum": ["SELLER", "BUYER"],
            },
            "status": {
                "type": "string",
                "description": (
                    "필터링할 단일 주문 상태 (선택, 하위호환). "
                    "QUOTE_REQUESTED / NEGOTIATING / CONFIRMED / "
                    "PREPARING / SHIPPING / COMPLETED / CANCELLED. "
                    "status_in 과 동시 지정 시 status_in 이 우선."
                ),
            },
            "status_in": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "QUOTE_REQUESTED", "NEGOTIATING", "CONFIRMED",
                        "PREPARING", "SHIPPING", "COMPLETED", "CANCELLED",
                    ],
                },
                "description": (
                    "다중 상태 필터 (선택, 권장). 사용자가 '진행 중', '활성', '내 주문' 등 "
                    "여러 상태를 한 번에 묻는 표현을 쓰면 "
                    "['QUOTE_REQUESTED','NEGOTIATING','CONFIRMED','PREPARING','SHIPPING'] 로 호출. "
                    "완료/취소는 명시적으로 요청한 경우에만 포함."
                ),
            },
        },
        "required": ["user_id", "role"],
    },
    groups=("inventory_order",),
)
def get_orders(
    user_id: str,
    role: str,
    status: Optional[str] = None,
    status_in: Optional[list[str]] = None,
) -> dict:
    """사용자의 주문 목록을 조회한다. role에 따라 buyer_id / seller_id로 필터링.

    조회는 order_service.list_orders 에 위임한다 — soft delete (deleted_at IS NULL)
    필터와 status_in 다중 상태 필터, 페이지네이션이 서비스 레이어에서 일관 처리된다.
    응답은 도구 전용으로 다시 평탄화 — LLM 이 참조하는 product_summary / primary_*
    /item_summary / items_count 필드를 유지한다 (orchestrator 시스템 프롬프트 라인
    1643-1644, 2542 가 이 필드명으로 주문 매칭/선택을 지시).

    파라미터:
      - user_id: 조회 대상 사용자 UUID (필수).
      - role:    "SELLER" 또는 "BUYER" (필수).
      - status:  단일 상태 필터 (선택, 하위호환). 예) "SHIPPING".
      - status_in: 다중 상태 필터 (선택, 권장). status 보다 우선 적용.
                   진행 중 주문은 ["QUOTE_REQUESTED","NEGOTIATING","CONFIRMED",
                   "PREPARING","SHIPPING"] 5종으로 호출 (완료/취소 제외).

    응답 키:
      - buyer_name / buyer_company / seller_name / seller_company
      - product_summary: "{첫 상품명}" 또는 "{첫 상품명} 외 N건" (items 비면 None)
      - primary_product_name / primary_quantity / primary_unit_price / primary_subtotal
      - item_summary: 모든 라인을 "이름 수량단위 x 단가원" 으로 join
      - items_count: order_items 길이
    임베딩 객체(buyer/seller/items)는 응답에서 제거 — LLM 토큰 절약.
    """
    try:
        if role not in ("SELLER", "BUYER"):
            return {
                "success": False,
                "error": f"invalid role: {role} (SELLER|BUYER)",
                "orders": [],
                "count": 0,
            }

        from app.services.order_service import order_service
        from app.services.agent_tools import _run_async_in_thread

        # order_service.list_orders 위임 — deleted_at IS NULL + status_in 일관 처리
        # status_in 이 있으면 list_orders 가 우선 적용, 없으면 단일 status fallback
        rows, _meta = _run_async_in_thread(
            lambda: order_service.list_orders(
                user_id=user_id,
                role=role,
                status=status,
                status_in=status_in,
                page=1,
                limit=20,
            )
        )

        # _flatten_order_row 가 buyer_name/seller_name 등 평탄 키를 이미 채워주고
        # items: [{quantity, unit_price, product_name, product_unit, ...}] 형태.
        # 도구 전용 summary 필드를 추가로 재가공한다.
        flattened: list[dict] = []
        for row in rows:
            items = row.pop("items", None) or []

            product_names: list[str] = []
            item_summaries: list[str] = []

            row["primary_product_name"] = None
            row["primary_quantity"] = None
            row["primary_unit_price"] = None
            row["primary_subtotal"] = None

            for idx, item in enumerate(items):
                if not isinstance(item, dict):
                    continue

                name = item.get("product_name")
                unit = item.get("product_unit") or "kg"
                quantity = item.get("quantity")
                unit_price = item.get("unit_price")

                if name:
                    product_names.append(name)

                    if quantity is not None and unit_price is not None:
                        item_summaries.append(f"{name} {quantity}{unit} x {unit_price:,}원")
                    elif quantity is not None:
                        item_summaries.append(f"{name} {quantity}{unit}")
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


@tool(
    name="get_order_detail",
    description=(
        "특정 주문의 상세 정보와 주문 항목(품목, 수량, 단가, 소계)을 함께 조회한다."
    ),
    parameters={
        "type": "object",
        "properties": {
            "order_id": {
                "type": "string",
                "description": "조회할 주문의 UUID",
            },
        },
        "required": ["order_id"],
    },
    groups=("inventory_order",),
)
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


@tool(
    name="update_order_status",
    description=(
        "주문의 진행 상태를 변경한다. order_id UUID 또는 order_number로 주문을 찾아 변경할 수 있다. "
        "판매자가 '출고 준비 완료', '배송 보냈어', '배송 시작했어', '납품 완료'라고 말하면 이 도구를 사용한다. "
        "상태 매핑: 출고 준비 완료=PREPARING, 배송 보냈어/배송 시작/출하 완료=SHIPPING, 납품 완료/배송 완료=COMPLETED. "
        "상태 변경 후 캘린더 일정은 자동 동기화된다. "
        "주의: SHIPPING, PREPARING, COMPLETED는 calendar event_type이 아니라 orders.status 값이다. "
        "[취소 전용] 사용자(구매자·판매자 모두)가 '주문 취소해줘', '이 주문 취소', '취소 처리해줘', '주문 없던 걸로 해줘' 등 "
        "취소 의사를 표현하면 반드시 이 도구를 new_status='CANCELLED'로 호출한다. "
        "delete_order는 취소 목적으로 절대 사용하지 않는다."
    ),
    parameters={
        "type": "object",
        "properties": {
            "order_id": {
                "type": "string",
                "description": "상태를 변경할 주문의 UUID. 모르면 빈 문자열로 두고 order_number를 사용한다.",
            },
            "order_number": {
                "type": "string",
                "description": "주문 번호. 예: ORD-20260502-3617. order_id를 모를 때 사용한다.",
            },
            "new_status": {
                "type": "string",
                "description": (
                    "변경할 상태값. "
                    "QUOTE_REQUESTED, NEGOTIATING, CONFIRMED, PREPARING, SHIPPING, COMPLETED, CANCELLED 중 하나."
                ),
            },
        },
        "required": ["new_status"],
    },
    groups=("inventory_order",),
)
def update_order_status(
    order_id: str = "",
    new_status: str = "",
    order_number: str = "",
) -> dict:
    """주문의 상태를 변경한다. 유효한 상태값인지 먼저 검증한다."""
    from app.services.agent_tools import (
        _UUID_PATTERN,
        _sync_calendar_events_for_order_id,
        _deduct_seller_stock_for_order,
    )

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


@tool(
    name="update_order",
    description="기존 주문의 수량·단가·납품일·메모를 수정한다. order_id 또는 order_number로 주문을 찾아 수정한다. subtotal과 total_amount는 자동 재계산된다.",
    parameters={
        "type": "object",
        "properties": {
            "order_id": {"type": "string", "description": "수정할 주문의 UUID (없으면 order_number 사용)"},
            "buyer_id": {"type": "string", "description": "구매자 UUID (권한 검증용)"},
            "order_number": {"type": "string", "description": "주문 번호 (예: ORD-20260502-8640). order_id 모를 때 사용"},
            "new_quantity": {"type": "integer", "description": "변경할 수량"},
            "new_unit_price": {"type": "integer", "description": "변경할 단가 (원)"},
            "delivery_date": {"type": "string", "description": "변경할 납품일 (YYYY-MM-DD)"},
            "notes": {"type": "string", "description": "변경할 메모/요청사항"},
        },
        "required": [],
    },
    groups=("inventory_order",),
    int_fields=frozenset({"new_quantity", "new_unit_price"}),
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
    from app.services.agent_tools import (
        _UUID_PATTERN,
        _sync_calendar_events_for_order_id,
    )

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


@tool(
    name="create_order",
    description=(
        "새 주문을 생성한다. "
        "[절대 주의 1] 사용자가 단순히 수량(예: 30kg)만 말했을 때는 절대 이 도구를 호출하지 마시오! "
        "수량만 입력된 경우 호출을 멈추고, 반드시 사용자에게 '판매자와 채팅방을 열어 조율할지, 아니면 바로 견적/주문을 넣을지' 물어봐야 한다. "
        "사용자가 명확하게 '바로 주문해', '그냥 넣어'라고 선택했을 때만 이 도구를 실행하라. "
        "[절대 주의 2 — 납품일] delivery_date 는 반드시 이번 대화에서 사용자가 직접 말한 날짜만 사용한다. "
        "사용자가 납품일을 말하지 않았다면 이 도구를 호출하지 말고 '납품일은 언제로 할까요? (예: 5월 20일)' 라고 먼저 물어봐라. "
        "'오늘', '내일', '다음 주' 처럼 모호한 표현을 LLM 임의로 날짜로 변환하거나 임의 날짜를 추측해 채우는 행위는 금지한다."
    ),
    parameters={
        "type": "object",
        "properties": {
            "buyer_id": {
                "type": "string",
                "description": (
                    "구매자의 UUID. 일반적으로 본인(현재 로그인 사용자)의 user_id 가 들어간다. "
                    "이름/회사명 같은 평문은 절대 그대로 넣지 말 것 — UUID 가 아닌 값을 넣으면 백엔드가 즉시 실패시킨다."
                ),
            },
            "seller_id": {
                "type": "string",
                "description": (
                    "판매자의 UUID. "
                    "사용자가 'test3', 'OO 농가', 'XX 도매상' 같이 이름이나 회사명으로만 지칭한 경우 "
                    "절대 그 이름을 그대로 이 필드에 넣지 마라. "
                    "반드시 먼저 get_user_profile(username='test3') 또는 get_user_profile(company_name='OO 농가') 또는 "
                    "find_sellers_by_product(category=..., product_name=...) 도구로 해당 사용자의 UUID를 조회한 뒤 그 user.id 를 사용해야 한다. "
                    "UUID가 아닌 값(이름·회사명·임의 문자열)을 넣으면 백엔드가 즉시 호출 실패로 처리한다. "
                    "0건 매칭이면 사용자에게 정확한 이름을 다시 물어봐라 (다른 거래처를 임의 추천하지 말 것)."
                ),
            },
            "product_id": {
                "type": "string",
                "description": "주문할 상품의 UUID. 정확한 UUID를 모른다면 '감자', '사과' 처럼 한글 상품명을 직접 입력해도 됩니다."
            },
            "quantity": {
                "type": "string",
                "description": "주문 수량",
            },
            "unit_price": {
                "type": "string",
                "description": "단위당 가격 (원)",
            },
            "delivery_date": {
                "type": "string",
                "description": (
                    "납품 희망일 (ISO 8601 형식: YYYY-MM-DD). "
                    "반드시 사용자가 이번 대화에서 직접 언급한 날짜만 입력한다. "
                    "사용자가 날짜를 말하지 않았으면 이 필드를 채우지 말고, "
                    "이 도구 자체를 호출하지 말고, '납품일은 언제로 할까요?' 라고 먼저 물어봐라."
                ),
            },
            "delivery_address": {
                "type": "string",
                "description": "납품 주소 (선택)",
            },
            "notes": {
                "type": "string",
                "description": "주문 관련 메모/요청사항 (선택)",
            },
        },
        "required": ["buyer_id", "seller_id", "product_id", "quantity", "unit_price"],
    },
    groups=("inventory_order",),
    int_fields=frozenset({"quantity", "unit_price"}),
)
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
    from app.services.agent_tools import (
        _UUID_PATTERN,
        _run_async_in_thread,
        _service_error_payload,
        _find_seller_by_name,
    )
    from .product import _find_product_by_name

    if not delivery_date or not isinstance(delivery_date, str) or not delivery_date.strip():
        return {
            "success": False,
            "error": "delivery_date 는 필수입니다. 사용자에게 납품일(YYYY-MM-DD)을 확인해주세요.",
        }
    try:
        supabase = get_supabase_client()

        # seller_id가 UUID가 아니면 이름/회사명으로 자동 검색
        if seller_id and not _UUID_PATTERN.match(str(seller_id)):
            lookup = _find_seller_by_name(supabase, str(seller_id))
            if not lookup["found"]:
                candidates = lookup.get("candidates", [])
                if candidates:
                    names = ", ".join(
                        f"{c.get('name') or c.get('company_name')}(ID:{c['id']})"
                        for c in candidates
                    )
                    return {
                        "success": False,
                        "llm_retry": True,
                        "error": (
                            f"'{seller_id}' 이름에 해당하는 판매자가 여럿입니다: {names}. "
                            "사용자에게 어느 판매자인지 확인한 뒤 seller_id=UUID 로 다시 호출하세요."
                        ),
                    }
                return {
                    "success": False,
                    "error": f"'{seller_id}' 판매자를 찾을 수 없습니다. 정확한 이름을 확인해주세요.",
                }
            seller_id = lookup["id"]

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


@tool(
    name="delete_order",
    description=(
        "주문을 완전히 숨긴다(soft delete — deleted_at 설정). "
        "잘못 생성된 주문·테스트 주문처럼 기록 자체를 제거해야 할 때만 사용한다. "
        "[절대 금지] 사용자가 '취소해줘', '취소 처리', '없던 걸로' 등 취소 의사를 표현한 경우에는 "
        "이 도구를 호출하지 마라. 취소는 반드시 update_order_status(new_status='CANCELLED')로 처리한다. "
        "이 도구로 삭제된 주문은 완료/취소 탭을 포함한 모든 화면에서 영구적으로 사라진다."
    ),
    parameters={
        "type": "object",
        "properties": {
            "order_id": {
                "type": "string",
                "description": "삭제할 주문의 UUID",
            },
            "user_id": {
                "type": "string",
                "description": "요청하는 사용자의 UUID (buyer_id 또는 seller_id와 일치해야 함)",
            },
        },
        "required": ["order_id", "user_id"],
    },
    groups=("inventory_order",),
)
def delete_order(order_id: str, user_id: str) -> dict:
    """주문을 삭제한다. buyer_id 또는 seller_id가 일치하는 경우만 가능."""
    from app.services.agent_tools import _sync_calendar_events_for_order_id

    try:
        supabase = get_supabase_client()

        # 주문 존재 및 권한 확인
        check = (
            supabase.table("orders")
            .select("id, order_number, buyer_id, seller_id, status")
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

        # soft-delete 전 status를 CANCELLED로 변경 — 안전망.
        # 이 도구는 진짜 삭제 전용이지만, 혹여 취소 목적으로 호출됐더라도
        # status=CANCELLED가 먼저 설정되어야 완료/취소 탭에서 보인다.
        # (deleted_at 설정 후에는 list_orders IS NULL 필터에 걸려 완전히 사라짐)
        current_status = order_data.get("status", "")
        if current_status not in ("CANCELLED", "COMPLETED"):
            supabase.table("orders").update({"status": "CANCELLED"}).eq("id", order_id).execute()
            _sync_calendar_events_for_order_id(order_id)

        supabase.table("orders").update({"deleted_at": now_utc}).eq("id", order_id).execute()

        # soft-delete 후에도 calendar_events 정리 — 사용자가 이미 CANCELLED/COMPLETED 주문을 삭제한 경우
        # 위 step의 status 분기를 거치지 않아 sync가 호출되지 않으므로 누락된 일정이 남는다.
        # _sync_calendar_events_for_order_sync 는 deleted_at 분기로 자동 soft-delete 처리.
        # sync 실패가 delete 자체를 막지 않도록 try/except 로 감싼다.
        try:
            _sync_calendar_events_for_order_id(order_id)
        except Exception as sync_err:
            print(
                f"[agent_tools.delete_order] calendar sync 실패 (무시): "
                f"order_id={order_id}, error={type(sync_err).__name__}: {sync_err}"
            )

        return {
            "success": True,
            "order_id": order_id,
            "order_number": order_data.get("order_number", ""),
            "message": f"주문 {order_data.get('order_number', '')}이 삭제되었습니다.",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
