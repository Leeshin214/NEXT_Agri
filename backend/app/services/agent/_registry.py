"""ToolRegistry — 도구 등록 / 조회 인프라.

도메인 모듈 (tools/product.py 등) 이 @tool 데코레이터로 함수를 등록하면
ToolRegistry 가 ToolEntry 인스턴스를 보관한다. orchestrator 는
function_map() / schemas_for(group) 로 조회.

같은 이름이 두 번 등록되면 RuntimeError (중복 방지).

PR 5 — int_fields 자동 추출 (2026-05-04):
- @tool(int_fields=...) 가 명시되지 않으면 함수 시그니처를 inspect 해
  int / Optional[int] 타입 어노테이션을 가진 인자를 자동 추출한다.
- 명시값과 자동값이 모두 있으면 명시값이 우선 (병행 fallback).
"""
from __future__ import annotations
import types
from dataclasses import dataclass, field
from typing import Callable, Union, get_args, get_origin, get_type_hints

@dataclass(frozen=True)
class ToolEntry:
    name: str
    func: Callable
    schema: dict           # {name, description, parameters} - OpenAI function call 형식
    groups: tuple[str, ...] # ("inventory_order",) | ("calendar",) | ("chat",)
    int_fields: frozenset[str] = field(default_factory=frozenset)


def _auto_int_fields(fn: Callable) -> frozenset[str]:
    """함수 시그니처에서 int / Optional[int] 타입 어노테이션 가진 인자를 추출.

    - `param: int`             -> 포함
    - `param: Optional[int]`   -> 포함 (Union[int, None])
    - `param: int | None`      -> 포함 (PEP 604 union type)
    - `param: str`             -> 제외
    - `param: list[int]`       -> 제외 (컨테이너 타입은 LLM 입력에서 직접 변환되지 않음)
    - 어노테이션 누락 / 평가 실패 시 안전하게 빈 frozenset 반환

    PR 5 자동화 — explicit int_fields 미지정 시 fallback 으로 사용.
    """
    try:
        hints = get_type_hints(fn)
    except Exception:
        # 어노테이션이 forward-ref string 으로 평가 실패하는 등 케이스에서
        # 데코레이터 적용을 막지 않도록 빈 set 으로 안전 폴백
        return frozenset()

    result: set[str] = set()
    for param_name, hint in hints.items():
        if param_name == "return":
            continue

        # 직접 int
        if hint is int:
            result.add(param_name)
            continue

        # Optional[int] / Union[int, None] (typing.Union) 또는 int | None (PEP 604, types.UnionType)
        # Python 3.10+ 에서 두 origin 이 다르므로 둘 다 검사한다.
        origin = get_origin(hint)
        if origin is Union or origin is types.UnionType:
            args = [a for a in get_args(hint) if a is not type(None)]
            if len(args) == 1 and args[0] is int:
                result.add(param_name)

    return frozenset(result)


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
    int_fields: frozenset[str] | None = None,
):
    """도구 함수에 붙이는 데코레이터.

    예:
        @tool(
            name="get_products",
            description="...",
            parameters={"type": "object", ...},
            groups=("inventory_order",),
            int_fields=frozenset({"quantity"}),  # 명시. 미지정 시 시그니처에서 자동 추출
        )
        def get_products(seller_id: str, quantity: int, ...) -> dict:
            ...

    함수 본문과 schema 가 같은 hunk 에 있어, 한 도구를 수정할 때
    다른 도구 / 다른 파일을 손대지 않아도 됨 (격리).

    int_fields:
      None (기본): 함수 시그니처에서 int / Optional[int] 인자를 자동 추출
      frozenset({...}): 명시 (자동 추출 무시)
      frozenset(): 빈 frozenset 명시 = "이 도구는 int 변환 대상 없음" 강제 선언
    """
    if not name:
        raise ValueError("tool name 필수")
    if not isinstance(groups, tuple) or not groups:
        raise ValueError(f"tool {name}: groups 는 비어있지 않은 tuple 이어야 함")

    def decorator(fn: Callable) -> Callable:
        # 명시값 우선; None 인 경우에만 자동 추출
        resolved_int_fields = (
            int_fields if int_fields is not None else _auto_int_fields(fn)
        )
        entry = ToolEntry(
            name=name,
            func=fn,
            schema={
                "name": name,
                "description": description,
                "parameters": parameters,
            },
            groups=groups,
            int_fields=resolved_int_fields,
        )
        ToolRegistry.register(entry)
        return fn

    return decorator
