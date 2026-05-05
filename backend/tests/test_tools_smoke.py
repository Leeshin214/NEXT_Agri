"""PR 5 — 도메인별 도구 smoke 테스트.

목적:
- 8 개 도메인 모듈 (product/order/partner/subscription/negotiation/user/calendar/chat)
  의 대표 도구가 ToolRegistry 에 등록되고 callable 로 호출 가능한지 확인.
- 각 도구의 schema (name/description/parameters) 가 OpenAI tool calling 형식으로
  올바른지 검증.
- 깊은 비즈니스 로직 (예: 모든 분기, RLS) 은 별도 사이클로 분리.

이 smoke 가 통과하면 "도구 격리 + 등록" 가 깨지지 않았다는 회귀 안전망이
확보된다. 반대로 도메인 모듈에서 import 오류·구문 오류·@tool 등록 누락이
발생하면 즉시 실패한다.
"""
from __future__ import annotations

import inspect
from typing import get_type_hints

from app.services.agent import (
    INT_FIELDS,
    TOOL_FUNCTION_MAP,
    TOOLS,
    TOOLS_CALENDAR,
    TOOLS_CHAT,
)
from app.services.agent._registry import ToolRegistry


# ─────────────────────────────────────────────
# 도메인별 핵심 도구 등록 검증 (PR 5 권장 smoke)
# ─────────────────────────────────────────────

# 도메인 → 대표 도구 (각 1~3 개씩, 총 15 개 sanity check)
_DOMAIN_TOOLS: dict[str, list[str]] = {
    "product":      ["get_products", "check_stock", "create_product"],
    "order":        ["get_orders", "create_order"],
    "partner":      ["find_alternative_partners", "get_partners"],
    "subscription": ["create_subscription_request", "accept_subscription_request"],
    "negotiation":  ["submit_counter_offer", "accept_counter_offer"],
    "user":         ["get_user_profile", "find_sellers_by_product"],
    "calendar":     ["get_calendar_events"],
    "chat":         ["get_chat_rooms", "get_chat_messages"],
}


def test_all_domain_modules_loaded():
    """모든 도메인 모듈 정상 import + 도구 등록."""
    for domain, tool_names in _DOMAIN_TOOLS.items():
        for name in tool_names:
            assert name in TOOL_FUNCTION_MAP, (
                f"도메인 {domain!r} 의 도구 {name!r} 가 ToolRegistry 에 없음 — "
                f"tools/{domain}.py import 실패 또는 @tool 등록 누락"
            )


def test_total_registered_tool_count():
    """PR 4 시점에 등록된 41 개 도구 그대로 유지 — 누락/중복 회귀 방지."""
    assert len(TOOL_FUNCTION_MAP) == 41, (
        f"등록된 도구 수가 41 개에서 변경됨: {len(TOOL_FUNCTION_MAP)}. "
        f"의도된 변경이면 이 테스트와 test_agent_registry.py 도 함께 수정."
    )


def test_groups_distribution():
    """그룹별 분류 — inventory_order 34 / calendar 4 / chat 3."""
    assert len(TOOLS) == 34, f"inventory_order 그룹: {len(TOOLS)}"
    assert len(TOOLS_CALENDAR) == 4, f"calendar 그룹: {len(TOOLS_CALENDAR)}"
    assert len(TOOLS_CHAT) == 3, f"chat 그룹: {len(TOOLS_CHAT)}"


# ─────────────────────────────────────────────
# OpenAI tool calling schema 형식 검증
# ─────────────────────────────────────────────

def test_all_tools_callable():
    """등록된 모든 도구가 callable — @tool 데코레이터가 함수 자체를 반환해야 함."""
    for name, fn in TOOL_FUNCTION_MAP.items():
        assert callable(fn), f"{name} 가 callable 이 아님"


def test_all_schemas_have_required_keys():
    """OpenAI tool calling 형식 — name/description/parameters 셋 다 필수."""
    for entry in ToolRegistry.all_entries().values():
        schema = entry.schema
        assert "name" in schema and schema["name"] == entry.name
        assert "description" in schema and isinstance(schema["description"], str)
        assert "parameters" in schema
        assert schema["parameters"].get("type") == "object", (
            f"{entry.name} parameters.type 이 'object' 가 아님"
        )


def test_all_schemas_in_groups_wrapped_correctly():
    """schemas_for(group) 결과는 {type:function, function:{...}} 형태."""
    for tools_list in (TOOLS, TOOLS_CALENDAR, TOOLS_CHAT):
        for item in tools_list:
            assert item.get("type") == "function"
            assert "function" in item
            fn_schema = item["function"]
            assert "name" in fn_schema
            assert "description" in fn_schema
            assert "parameters" in fn_schema


# ─────────────────────────────────────────────
# 도메인별 시그니처 sanity (한 도구씩, 회귀 자동 감지)
# ─────────────────────────────────────────────

def test_get_products_signature():
    fn = TOOL_FUNCTION_MAP["get_products"]
    sig = inspect.signature(fn)
    params = list(sig.parameters.keys())
    assert "seller_id" in params
    assert "category" in params


def test_create_order_signature_required_params():
    """create_order 는 buyer_id/seller_id/product_id/quantity/unit_price/delivery_date 필수."""
    fn = TOOL_FUNCTION_MAP["create_order"]
    sig = inspect.signature(fn)
    params = sig.parameters
    for required in ("buyer_id", "seller_id", "product_id", "quantity", "unit_price", "delivery_date"):
        assert required in params, f"create_order 에 {required} 파라미터가 없음"


def test_find_alternative_partners_signature():
    fn = TOOL_FUNCTION_MAP["find_alternative_partners"]
    sig = inspect.signature(fn)
    params = sig.parameters
    assert "user_id" in params
    assert "role" in params
    assert "category" in params


def test_create_subscription_request_signature():
    fn = TOOL_FUNCTION_MAP["create_subscription_request"]
    sig = inspect.signature(fn)
    params = sig.parameters
    for required in ("user_id", "target_user_id", "frequency", "start_date", "items"):
        assert required in params


def test_submit_counter_offer_signature():
    fn = TOOL_FUNCTION_MAP["submit_counter_offer"]
    sig = inspect.signature(fn)
    params = sig.parameters
    assert "user_id" in params
    assert "order_id" in params
    assert "proposed_total_amount" in params


def test_get_user_profile_signature_all_optional():
    """get_user_profile 은 세 파라미터 모두 default 가 있어야 함 (둘 중 하나 이상으로 검색)."""
    fn = TOOL_FUNCTION_MAP["get_user_profile"]
    sig = inspect.signature(fn)
    for name in ("user_id", "username", "company_name"):
        param = sig.parameters[name]
        assert param.default != inspect.Parameter.empty, (
            f"get_user_profile.{name} 가 default 없는 필수 파라미터로 변경됨"
        )


def test_get_calendar_events_signature_int_year_month():
    """get_calendar_events.year/month 가 int 어노테이션 — 자동 INT_FIELDS 추출 대상.

    도메인 모듈은 `from __future__ import annotations` 를 사용해 어노테이션이
    문자열로 보존되므로 raw __annotations__ 로는 비교 불가 — get_type_hints 로
    실제 타입 객체로 평가한 뒤 비교한다.
    """
    fn = TOOL_FUNCTION_MAP["get_calendar_events"]
    hints = get_type_hints(fn)
    assert hints.get("year") is int
    assert hints.get("month") is int


def test_get_chat_rooms_signature():
    fn = TOOL_FUNCTION_MAP["get_chat_rooms"]
    sig = inspect.signature(fn)
    assert "user_id" in sig.parameters


def test_get_chat_messages_limit_int():
    """get_chat_messages.limit 은 int — auto INT_FIELDS 가 limit 을 잡아야 함."""
    fn = TOOL_FUNCTION_MAP["get_chat_messages"]
    hints = get_type_hints(fn)
    assert hints.get("limit") is int
    # 자동 추출이 limit 을 INT_FIELDS 합집합에 포함시켰는지도 같이 검증
    assert "limit" in INT_FIELDS


# ─────────────────────────────────────────────
# 외부 import 안정성 (chat_ws.py 등에서 직접 참조하는 함수)
# ─────────────────────────────────────────────

def test_analyze_chat_consensus_importable_but_not_registered():
    """chat_ws.py 에서 직접 import 하지만 LLM 도구는 아님 — registry 미등록 + 모듈 callable.

    이 smoke 가 깨지면 chat_ws.py 임포트도 깨진다.
    """
    from app.services.agent.tools import chat as chat_module
    assert callable(chat_module.analyze_chat_consensus)
    assert "analyze_chat_consensus" not in TOOL_FUNCTION_MAP


def test_find_product_by_name_helper_importable():
    """product 도메인 헬퍼 — order/subscription 모듈이 lazy import 로 사용."""
    from app.services.agent.tools.product import _find_product_by_name
    assert callable(_find_product_by_name)


def test_shared_helpers_importable():
    """_shared 모듈의 cross-domain helper — 도구가 lazy import 로 사용."""
    from app.services.agent._shared import (
        _UUID_PATTERN,
        _run_async_in_thread,
        _service_error_payload,
        _sync_calendar_events_for_order_id,
    )
    # smoke — 함수 자체가 callable / 패턴 객체가 truthy
    assert _UUID_PATTERN.match("11111111-1111-1111-1111-111111111111")
    assert callable(_run_async_in_thread)
    assert callable(_service_error_payload)
    assert callable(_sync_calendar_events_for_order_id)
