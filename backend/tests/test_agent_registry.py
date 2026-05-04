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
# PR 1 — 6 개 도메인 모듈 등록 검증
# (fixture 가 registry 를 비우므로, 별도 fixture 없이 직접 import 검증)
# ─────────────────────────────────────────────


def test_domain_modules_register_33_tools(_reset_registry=None):  # noqa: ARG001
    """PR 1: product/order/partner/subscription/negotiation/user 6 모듈 import 시 총 33 개 도구 등록."""
    # 새로 import 하기 위해 sys.modules 초기화
    import importlib
    import sys
    for mod in [
        "app.services.agent",
        "app.services.agent.tools",
        "app.services.agent.tools.product",
        "app.services.agent.tools.order",
        "app.services.agent.tools.partner",
        "app.services.agent.tools.subscription",
        "app.services.agent.tools.negotiation",
        "app.services.agent.tools.user",
    ]:
        sys.modules.pop(mod, None)

    # registry 도 비워야 import 시 다시 등록됨
    ToolRegistry._items.clear()

    agent = importlib.import_module("app.services.agent")
    assert len(agent.TOOL_FUNCTION_MAP) == 33
    assert len(agent.TOOLS) == 33  # 모두 inventory_order 그룹
    assert len(agent.TOOLS_CALENDAR) == 0  # PR 2
    assert len(agent.TOOLS_CHAT) == 0  # PR 3

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
        # subscription
        "create_subscription_request", "accept_subscription_request",
        "reject_subscription_request", "create_subscription_from_order",
        # negotiation
        "submit_counter_offer", "accept_counter_offer", "reject_counter_offer",
        "submit_delivery_date_change", "accept_delivery_date_change",
        "reject_delivery_date_change",
        # user
        "get_user_profile", "find_sellers_by_product",
        "find_buyers_by_product", "open_chat_room",
    }
    assert set(agent.TOOL_FUNCTION_MAP.keys()) == expected


def test_domain_modules_int_fields_union(_reset_registry=None):  # noqa: ARG001
    """PR 1: 도메인 모듈 등록 후 INT_FIELDS 합집합 검증."""
    import importlib
    import sys
    for mod in [
        "app.services.agent",
        "app.services.agent.tools",
        "app.services.agent.tools.product",
        "app.services.agent.tools.order",
        "app.services.agent.tools.partner",
        "app.services.agent.tools.subscription",
        "app.services.agent.tools.negotiation",
        "app.services.agent.tools.user",
    ]:
        sys.modules.pop(mod, None)
    ToolRegistry._items.clear()

    agent = importlib.import_module("app.services.agent")
    # 각 도메인이 신고한 int_fields 의 합집합 확인 (orchestrator INT_FIELDS 와 호환되어야 함)
    expected_subset = {
        "new_quantity", "price_per_unit", "stock_quantity", "min_order_qty",
        "quantity", "unit_price", "new_unit_price", "proposed_total_amount",
    }
    assert expected_subset.issubset(agent.INT_FIELDS)
