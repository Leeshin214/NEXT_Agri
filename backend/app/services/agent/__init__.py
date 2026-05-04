"""AgriFlow AI 에이전트 도구 모듈.

도구는 도메인별 모듈 (tools/product.py, tools/order.py, ...) 에 정의되며,
@tool 데코레이터로 ToolRegistry 에 자동 등록된다.

이 패키지를 import 하는 시점에 모든 도메인 모듈이 import 되어 등록이
완료된다 (tools/__init__.py 가 명시적으로 모든 모듈 import).

외부 (orchestrator.py 등) 는 다음만 사용:
- TOOL_FUNCTION_MAP : 이름 → 함수
- TOOLS, TOOLS_CALENDAR, TOOLS_CHAT : OpenAI tool calling schema (그룹별)
- INT_FIELDS : 정수 변환 대상 필드명 합집합
"""
from . import tools  # noqa: F401 — 등록 트리거
from ._registry import ToolRegistry

TOOL_FUNCTION_MAP = ToolRegistry.function_map()
TOOLS = ToolRegistry.schemas_for("inventory_order")
TOOLS_CALENDAR = ToolRegistry.schemas_for("calendar")
TOOLS_CHAT = ToolRegistry.schemas_for("chat")
INT_FIELDS = ToolRegistry.int_fields_union()

__all__ = [
    "TOOL_FUNCTION_MAP",
    "TOOLS",
    "TOOLS_CALENDAR",
    "TOOLS_CHAT",
    "INT_FIELDS",
    "ToolRegistry",
]
