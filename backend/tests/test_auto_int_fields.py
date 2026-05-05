"""PR 5 — _auto_int_fields 자동 추출 단위 테스트.

PR 5 에서 @tool 데코레이터가 명시 int_fields 미지정 시 함수 시그니처 어노테이션을
inspect 해서 자동 추출하도록 변경되었다. 이 모듈은 자동 추출 로직 그 자체와
실제 도메인 모듈에 적용된 결과를 검증한다.
"""
from __future__ import annotations

from typing import Optional, Union

import pytest

from app.services.agent._registry import (
    ToolRegistry,
    _auto_int_fields,
    tool,
)


# ─────────────────────────────────────────────
# 자동 추출 로직 단위 검증 — registry 와 무관한 raw 함수
# ─────────────────────────────────────────────

def test_auto_int_fields_plain_int():
    def fn(a: int, b: str) -> dict:
        return {}
    assert _auto_int_fields(fn) == frozenset({"a"})


def test_auto_int_fields_optional_int():
    def fn(a: int, b: Optional[int] = None) -> dict:
        return {}
    assert _auto_int_fields(fn) == frozenset({"a", "b"})


def test_auto_int_fields_union_int_none():
    def fn(a: Union[int, None] = None) -> dict:
        return {}
    assert _auto_int_fields(fn) == frozenset({"a"})


def test_auto_int_fields_pep604_pipe_union():
    """`int | None` (PEP 604) 도 자동 추출 — Python 3.10+."""
    def fn(a: int | None = None, b: str = "") -> dict:
        return {}
    assert _auto_int_fields(fn) == frozenset({"a"})


def test_auto_int_fields_str_excluded():
    def fn(a: str, b: str = "") -> dict:
        return {}
    assert _auto_int_fields(fn) == frozenset()


def test_auto_int_fields_default_value_with_int_annotation():
    """`x: int = 0` — 어노테이션이 int 면 default 가 0 이어도 추출."""
    def fn(x: int = 0, y: int = 20) -> dict:
        return {}
    assert _auto_int_fields(fn) == frozenset({"x", "y"})


def test_auto_int_fields_no_annotation_excluded():
    """타입 어노테이션이 없으면 자동 추출 대상 아님."""
    def fn(a, b=0) -> dict:  # noqa: ANN001
        return {}
    assert _auto_int_fields(fn) == frozenset()


def test_auto_int_fields_list_int_excluded():
    """list[int] 같은 컨테이너 타입은 LLM 입력에서 직접 변환되지 않으므로 제외."""
    def fn(items: list[int]) -> dict:
        return {}
    assert _auto_int_fields(fn) == frozenset()


def test_auto_int_fields_optional_list_int_excluded():
    def fn(items: Optional[list[int]] = None) -> dict:
        return {}
    assert _auto_int_fields(fn) == frozenset()


def test_auto_int_fields_return_type_excluded():
    """return 어노테이션은 항상 무시."""
    def fn(a: int) -> int:
        return a
    assert _auto_int_fields(fn) == frozenset({"a"})


def test_auto_int_fields_failure_returns_empty():
    """get_type_hints 가 실패하는 케이스 (forward-ref 등) 에서 안전하게 빈 set."""
    # forward-ref 형태로 평가 실패 유도. NameError 가 발생해야 한다.
    def fn(a: "NotARealType") -> dict:  # noqa: F821
        return {}
    # _auto_int_fields 내부 try/except 가 잡아 빈 set 반환
    assert _auto_int_fields(fn) == frozenset()


# ─────────────────────────────────────────────
# 데코레이터 통합 — 명시 vs 자동 우선순위 검증
# ─────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_registry():
    saved = dict(ToolRegistry._items)
    ToolRegistry._items.clear()
    yield
    ToolRegistry._items.clear()
    ToolRegistry._items.update(saved)


def test_tool_decorator_auto_extracts_when_int_fields_omitted():
    @tool(
        name="auto_one",
        description="x",
        parameters={"type": "object"},
        groups=("g",),
    )
    def fn(quantity: int, name: str) -> dict:
        return {}

    entry = ToolRegistry.all_entries()["auto_one"]
    assert entry.int_fields == frozenset({"quantity"})


def test_tool_decorator_explicit_overrides_auto():
    """명시된 int_fields 가 자동 추출 결과와 다르면 명시값 그대로 사용."""
    @tool(
        name="explicit_one",
        description="x",
        parameters={"type": "object"},
        groups=("g",),
        int_fields=frozenset({"forced_field"}),
    )
    def fn(quantity: int, forced_field: str) -> dict:
        return {}

    entry = ToolRegistry.all_entries()["explicit_one"]
    # quantity 는 자동 추출 대상이지만, 명시값이 우선이라 무시
    assert entry.int_fields == frozenset({"forced_field"})


def test_tool_decorator_empty_explicit_disables_auto():
    """frozenset() 명시는 '자동 추출 끄기' 의미 — None 과 구분."""
    @tool(
        name="empty_one",
        description="x",
        parameters={"type": "object"},
        groups=("g",),
        int_fields=frozenset(),
    )
    def fn(quantity: int) -> dict:
        return {}

    entry = ToolRegistry.all_entries()["empty_one"]
    # 자동 추출 대상이지만 빈 frozenset 명시했으므로 비어 있어야 함
    assert entry.int_fields == frozenset()


def test_tool_decorator_no_int_params_auto_yields_empty():
    @tool(
        name="no_int",
        description="x",
        parameters={"type": "object"},
        groups=("g",),
    )
    def fn(name: str, kind: str = "x") -> dict:
        return {}

    entry = ToolRegistry.all_entries()["no_int"]
    assert entry.int_fields == frozenset()


# ─────────────────────────────────────────────
# 실제 도메인 모듈 적용 결과 — 기존 명시값과 일치 또는 superset 보장
# ─────────────────────────────────────────────

# PR 4 시점에 알려진 명시 int_fields — 자동화 후에도 이 값들은 모두 포함되어야 한다.
# (PR 5 자동화는 추가 필드만 더하고, 기존 명시값은 어떤 경우에도 빠지면 안 됨)
_KNOWN_EXPLICIT_INT_FIELDS = {
    # product
    "new_quantity",       # update_stock
    "price_per_unit",     # create_product / update_product
    "stock_quantity",     # create_product
    "min_order_qty",      # create_product
    # order
    "new_unit_price",     # update_order
    "quantity",           # create_order
    "unit_price",         # create_order
    # negotiation
    "proposed_total_amount",  # submit_counter_offer
}


def test_domain_modules_explicit_int_fields_preserved():
    """PR 5 자동화 후에도 모든 기존 명시 int_fields 는 INT_FIELDS 합집합에 포함되어야 한다."""
    # 도메인 모듈 강제 reload — registry 비웠으므로 다시 import
    import importlib
    import sys

    pr5_modules = [
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
    for mod in pr5_modules:
        sys.modules.pop(mod, None)

    agent = importlib.import_module("app.services.agent")
    assert _KNOWN_EXPLICIT_INT_FIELDS.issubset(agent.INT_FIELDS)


def test_domain_modules_auto_extracts_year_month_limit():
    """PR 5: 자동 추출로 새로 잡히는 필드 — get_calendar_events.year/month, get_chat_messages.limit.

    이전엔 orchestrator.execute_tool 안에 하드코딩된 INT_FIELDS 에 year/month 만 있었고
    limit 은 누락되어 있었다. 자동 추출로 registry 차원에서 통합.
    """
    import importlib
    import sys

    pr5_modules = [
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
    for mod in pr5_modules:
        sys.modules.pop(mod, None)

    agent = importlib.import_module("app.services.agent")
    assert {"year", "month", "limit"}.issubset(agent.INT_FIELDS)
