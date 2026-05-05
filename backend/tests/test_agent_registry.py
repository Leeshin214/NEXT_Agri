"""ToolRegistry 인프라 단위 테스트.

PR 0 검증 목적:
- 데코레이터로 함수 등록이 동작하는가
- function_map / schemas_for / int_fields_union 정상 작동하는가
- 중복 등록 시 RuntimeError 가 나는가
- 빈 그룹 조회 시 빈 리스트 반환하는가
"""
import pytest
from app.services.agent._registry import ToolRegistry, ToolEntry, tool


@pytest.fixture(autouse=True)
def _reset_registry():
    """각 테스트마다 registry 초기화 (모듈 글로벌 상태)."""
    saved = dict(ToolRegistry._items)
    ToolRegistry._items.clear()
    yield
    ToolRegistry._items.clear()
    ToolRegistry._items.update(saved)


def test_register_and_lookup():
    @tool(
        name="dummy_get",
        description="테스트용",
        parameters={"type": "object", "properties": {}, "required": []},
        groups=("inventory_order",),
    )
    def dummy_get():
        return {"ok": True}

    fmap = ToolRegistry.function_map()
    assert "dummy_get" in fmap
    assert fmap["dummy_get"]() == {"ok": True}

    schemas = ToolRegistry.schemas_for("inventory_order")
    assert len(schemas) == 1
    assert schemas[0]["function"]["name"] == "dummy_get"


def test_duplicate_registration_raises():
    @tool(name="dup", description="x", parameters={"type": "object"}, groups=("g",))
    def first():
        pass

    with pytest.raises(RuntimeError, match="중복 등록"):
        @tool(name="dup", description="x", parameters={"type": "object"}, groups=("g",))
        def second():
            pass


def test_schemas_for_unknown_group_returns_empty():
    @tool(name="x", description="x", parameters={"type": "object"}, groups=("g1",))
    def fn():
        pass

    assert ToolRegistry.schemas_for("nonexistent_group") == []


def test_int_fields_union():
    @tool(
        name="a", description="x", parameters={"type": "object"},
        groups=("g",), int_fields=frozenset({"a", "b"}),
    )
    def fn_a():
        pass

    @tool(
        name="b", description="x", parameters={"type": "object"},
        groups=("g",), int_fields=frozenset({"b", "c"}),
    )
    def fn_b():
        pass

    union = ToolRegistry.int_fields_union()
    assert union == frozenset({"a", "b", "c"})


def test_empty_groups_raises():
    with pytest.raises(ValueError, match="groups"):
        @tool(name="x", description="x", parameters={"type": "object"}, groups=())
        def fn():
            pass


def test_groups_must_be_tuple():
    with pytest.raises(ValueError, match="groups"):
        @tool(name="x", description="x", parameters={"type": "object"}, groups=["g"])  # type: ignore[arg-type]
        def fn():
            pass


def test_multi_group_registration():
    @tool(
        name="multi",
        description="x",
        parameters={"type": "object"},
        groups=("g1", "g2"),
    )
    def fn():
        pass

    assert len(ToolRegistry.schemas_for("g1")) == 1
    assert len(ToolRegistry.schemas_for("g2")) == 1
    assert ToolRegistry.schemas_for("g1")[0]["function"]["name"] == "multi"


# ─────────────────────────────────────────────
# PR 1+2+3 — 8 개 도메인 모듈 등록 검증
# (fixture 가 registry 를 비우므로, 별도 fixture 없이 직접 import 검증)
# ─────────────────────────────────────────────

# PR 3 시점에 등록되는 모든 도메인 모듈 — 재 import 시 sys.modules.pop() 대상.
_PR3_DOMAIN_MODULES = [
    "app.services.agent",
    "app.services.agent.tools",
    "app.services.agent.tools.product",
    "app.services.agent.tools.order",
    "app.services.agent.tools.partner",
    "app.services.agent.tools.subscription",
    "app.services.agent.tools.negotiation",
    "app.services.agent.tools.user",
    "app.services.agent.tools.calendar",
    "app.services.agent.tools.chat",
]


def test_domain_modules_register_42_tools(_reset_registry=None):  # noqa: ARG001
    """PR 1+2+3+4+5: 8 개 도메인 모듈 import 시 총 42 개 도구 등록 (35 inventory_order + 4 calendar + 3 chat).

    PR 5 에서 subscription 도메인에 get_subscriptions 가 추가되어
    inventory_order 34 → 35, 전체 41 → 42.
    """
    # 새로 import 하기 위해 sys.modules 초기화
    import importlib
    import sys
    for mod in _PR3_DOMAIN_MODULES:
        sys.modules.pop(mod, None)

    # registry 도 비워야 import 시 다시 등록됨
    ToolRegistry._items.clear()

    agent = importlib.import_module("app.services.agent")
    assert len(agent.TOOL_FUNCTION_MAP) == 42
    assert len(agent.TOOLS) == 35  # inventory_order 그룹 (PR 5: subscription 6)
    assert len(agent.TOOLS_CALENDAR) == 4  # PR 2 — calendar 그룹
    assert len(agent.TOOLS_CHAT) == 3  # PR 3 — chat 그룹

    # 도메인별 핵심 함수가 등록되어 있는지 sanity check
    expected = {
        # product
        "get_products", "check_stock", "update_stock",
        "create_product", "delete_product", "update_product",
        # order
        "get_orders", "get_order_detail", "update_order_status",
        "update_order", "create_order", "delete_order",
        # partner
        "find_alternative_partners", "request_partner_registration",
        "request_partner_registration_by_name", "get_partners",
        "get_incoming_partner_requests", "accept_partner_request",
        "reject_partner_request",
        # subscription (PR 4: get_incoming_subscription_requests, PR 5: get_subscriptions)
        "create_subscription_request", "accept_subscription_request",
        "reject_subscription_request", "create_subscription_from_order",
        "get_incoming_subscription_requests", "get_subscriptions",
        # negotiation
        "submit_counter_offer", "accept_counter_offer", "reject_counter_offer",
        "submit_delivery_date_change", "accept_delivery_date_change",
        "reject_delivery_date_change",
        # user
        "get_user_profile", "find_sellers_by_product",
        "find_buyers_by_product", "open_chat_room",
        # calendar (PR 2)
        "get_calendar_events", "create_calendar_event",
        "update_calendar_event", "delete_calendar_event",
        # chat (PR 3)
        "get_chat_rooms", "get_chat_messages", "send_chat_message",
    }
    assert set(agent.TOOL_FUNCTION_MAP.keys()) == expected


def test_calendar_tools_in_calendar_group_only(_reset_registry=None):  # noqa: ARG001
    """PR 2: calendar 도구 4 개는 'calendar' 그룹에만 속하고 'inventory_order' 에는 없어야 한다."""
    import importlib
    import sys
    for mod in _PR3_DOMAIN_MODULES:
        sys.modules.pop(mod, None)
    ToolRegistry._items.clear()

    agent = importlib.import_module("app.services.agent")

    inventory_order_names = {t["function"]["name"] for t in agent.TOOLS}
    calendar_names = {t["function"]["name"] for t in agent.TOOLS_CALENDAR}

    calendar_tools = {
        "get_calendar_events", "create_calendar_event",
        "update_calendar_event", "delete_calendar_event",
    }
    assert calendar_tools == calendar_names
    assert calendar_tools.isdisjoint(inventory_order_names)


def test_chat_tools_in_chat_group_only(_reset_registry=None):  # noqa: ARG001
    """PR 3: chat 도구 3 개는 'chat' 그룹에만 속하고 'inventory_order'/'calendar' 에는 없어야 한다."""
    import importlib
    import sys
    for mod in _PR3_DOMAIN_MODULES:
        sys.modules.pop(mod, None)
    ToolRegistry._items.clear()

    agent = importlib.import_module("app.services.agent")

    inventory_order_names = {t["function"]["name"] for t in agent.TOOLS}
    calendar_names = {t["function"]["name"] for t in agent.TOOLS_CALENDAR}
    chat_names = {t["function"]["name"] for t in agent.TOOLS_CHAT}

    chat_tools = {"get_chat_rooms", "get_chat_messages", "send_chat_message"}
    assert chat_tools == chat_names
    assert chat_tools.isdisjoint(inventory_order_names)
    assert chat_tools.isdisjoint(calendar_names)


def test_analyze_chat_consensus_not_registered(_reset_registry=None):  # noqa: ARG001
    """PR 3: analyze_chat_consensus 는 LLM 도구가 아니므로 ToolRegistry 에 등록되지 않아야 한다.
    chat_ws.py 가 직접 import 해서 호출하는 함수.
    """
    import importlib
    import sys
    for mod in _PR3_DOMAIN_MODULES:
        sys.modules.pop(mod, None)
    ToolRegistry._items.clear()

    agent = importlib.import_module("app.services.agent")
    assert "analyze_chat_consensus" not in agent.TOOL_FUNCTION_MAP

    # 단, 같은 모듈에서 callable 로 import 가능해야 한다
    chat_module = importlib.import_module("app.services.agent.tools.chat")
    assert callable(chat_module.analyze_chat_consensus)


def test_domain_modules_int_fields_union(_reset_registry=None):  # noqa: ARG001
    """PR 1+2+3: 도메인 모듈 등록 후 INT_FIELDS 합집합 검증."""
    import importlib
    import sys
    for mod in _PR3_DOMAIN_MODULES:
        sys.modules.pop(mod, None)
    ToolRegistry._items.clear()

    agent = importlib.import_module("app.services.agent")
    # 각 도메인이 신고한 int_fields 의 합집합 확인 (orchestrator INT_FIELDS 와 호환되어야 함)
    expected_subset = {
        "new_quantity", "price_per_unit", "stock_quantity", "min_order_qty",
        "quantity", "unit_price", "new_unit_price", "proposed_total_amount",
    }
    assert expected_subset.issubset(agent.INT_FIELDS)
