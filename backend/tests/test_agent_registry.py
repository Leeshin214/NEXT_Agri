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
