"""ToolRegistry — 도구 등록 / 조회 인프라.

도메인 모듈 (tools/product.py 등) 이 @tool 데코레이터로 함수를 등록하면
ToolRegistry 가 ToolEntry 인스턴스를 보관한다. orchestrator 는
function_map() / schemas_for(group) 로 조회.

같은 이름이 두 번 등록되면 RuntimeError (중복 방지).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable

@dataclass(frozen=True)
class ToolEntry:
    name: str
    func: Callable
    schema: dict           # {name, description, parameters} - OpenAI function call 형식
    groups: tuple[str, ...] # ("inventory_order",) | ("calendar",) | ("chat",)
    int_fields: frozenset[str] = field(default_factory=frozenset)


class ToolRegistry:
    """모듈 import 시 @tool 데코레이터가 호출하는 글로벌 레지스트리."""
    _items: dict[str, ToolEntry] = {}

    @classmethod
    def register(cls, entry: ToolEntry) -> None:
        if entry.name in cls._items:
            raise RuntimeError(
                f"ToolRegistry 중복 등록 시도: {entry.name} "
                f"(이미 등록된 함수: {cls._items[entry.name].func.__module__})"
            )
        cls._items[entry.name] = entry

    @classmethod
    def function_map(cls) -> dict[str, Callable]:
        return {name: entry.func for name, entry in cls._items.items()}

    @classmethod
    def schemas_for(cls, group: str) -> list[dict]:
        """OpenAI tool calling 형식으로 묶어 반환."""
        return [
            {"type": "function", "function": entry.schema}
            for entry in cls._items.values()
            if group in entry.groups
        ]

    @classmethod
    def int_fields_union(cls) -> frozenset[str]:
        result: set[str] = set()
        for entry in cls._items.values():
            result.update(entry.int_fields)
        return frozenset(result)

    @classmethod
    def all_entries(cls) -> dict[str, ToolEntry]:
        return dict(cls._items)


def tool(
    *,
    name: str,
    description: str,
    parameters: dict,
    groups: tuple[str, ...],
    int_fields: frozenset[str] = frozenset(),
):
    """도구 함수에 붙이는 데코레이터.

    예:
        @tool(
            name="get_products",
            description="...",
            parameters={"type": "object", ...},
            groups=("inventory_order",),
            int_fields=frozenset({"quantity"}),
        )
        def get_products(seller_id: str, ...) -> dict:
            ...

    함수 본문과 schema 가 같은 hunk 에 있어, 한 도구를 수정할 때
    다른 도구 / 다른 파일을 손대지 않아도 됨 (격리).
    """
    if not name:
        raise ValueError("tool name 필수")
    if not isinstance(groups, tuple) or not groups:
        raise ValueError(f"tool {name}: groups 는 비어있지 않은 tuple 이어야 함")

    def decorator(fn: Callable) -> Callable:
        entry = ToolEntry(
            name=name,
            func=fn,
            schema={
                "name": name,
                "description": description,
                "parameters": parameters,
            },
            groups=groups,
            int_fields=int_fields,
        )
        ToolRegistry.register(entry)
        return fn

    return decorator
