"""
orchestrator.py — LangGraph StateGraph 기반 오케스트레이터

동작 흐름:
  1. orchestrator_node: LLM이 사용자 메시지를 보고 intent 분류 + 필요한 tool 선택
  2. inventory_order_node: tool 실행 (agent_tools.py 함수 호출)
  3. response_node: tool 결과를 바탕으로 최종 답변 생성

라우팅:
  - orchestrator_node 후: intent가 INVENTORY/ORDER면 inventory_order_node, 아니면 response_node
  - inventory_order_node 후: 추가 tool이 필요하면 orchestrator_node로 복귀, 아니면 response_node

Groq API는 OpenAI 호환 인터페이스를 사용하므로,
메시지 구조는 role: "tool" + tool_call_id 형식이다.
"""

import json
import operator
from typing import Any, Annotated

from groq import AsyncGroq
from langgraph.graph import StateGraph, END
from typing import TypedDict, Optional

from app.core.config import settings
from app.services.agent_tools import TOOL_FUNCTION_MAP


# ─────────────────────────────────────────────
# AgentState 정의
# ─────────────────────────────────────────────

class AgentState(TypedDict):
    user_id: str
    user_role: str           # SELLER / BUYER
    user_info: dict          # name, company_name
    message: str             # 사용자 입력
    intent: str              # INVENTORY / ORDER / GENERAL
    messages: Annotated[list, operator.add]  # LLM 메시지 히스토리
    tool_results: list       # 실행된 tool 결과들
    tools_used: list         # 사용된 tool 이름들
    final_response: str      # 최종 답변
    tool_round: int          # tool 실행 라운드 카운터 (무한루프 방지)


# ─────────────────────────────────────────────
# Groq(OpenAI 호환) API에 전달할 tools 정의
# ─────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_products",
            "description": (
                "판매자의 상품 및 재고 목록을 조회한다. "
                "전체 상품을 보거나 특정 카테고리(예: 과일, 채소)만 필터링할 수 있다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "seller_id": {
                        "type": "string",
                        "description": "판매자의 UUID (현재 로그인한 판매자 ID)",
                    },
                    "category": {
                        "type": "string",
                        "description": "필터링할 카테고리명 (선택). 없으면 전체 조회.",
                    },
                },
                "required": ["seller_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_stock",
            "description": (
                "특정 상품 ID로 재고 수량, 단위, 상태(NORMAL/LOW_STOCK/OUT_OF_STOCK)를 확인한다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "string",
                        "description": "조회할 상품의 UUID",
                    },
                },
                "required": ["product_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_stock",
            "description": (
                "특정 상품의 재고 수량을 새 값으로 업데이트한다. "
                "수량에 따라 상태(NORMAL/LOW_STOCK/OUT_OF_STOCK)가 자동으로 변경된다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "string",
                        "description": "재고를 수정할 상품의 UUID",
                    },
                    "new_quantity": {
                        "type": "string",
                        "description": "변경할 재고 수량 (0 이상의 정수)",
                    },
                },
                "required": ["product_id", "new_quantity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_product",
            "description": (
                "새 상품을 등록한다. "
                "상품명, 카테고리, 단가, 재고수량, 단위는 필수. "
                "산지, 규격, 최소주문수량, 설명은 선택사항."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "seller_id": {
                        "type": "string",
                        "description": "판매자의 UUID (현재 로그인한 판매자 ID)",
                    },
                    "name": {
                        "type": "string",
                        "description": "상품명 (예: 사과, 배추, 토마토)",
                    },
                    "category": {
                        "type": "string",
                        "description": "카테고리 (예: FRUIT, VEGETABLE, GRAIN)",
                    },
                    "price_per_unit": {
                        "type": "string",
                        "description": "단위당 가격 (원)",
                    },
                    "stock_quantity": {
                        "type": "string",
                        "description": "초기 재고 수량",
                    },
                    "unit": {
                        "type": "string",
                        "description": "판매 단위 (예: kg, box, 개, 포대)",
                    },
                    "origin": {
                        "type": "string",
                        "description": "산지/원산지 (선택, 예: 나주, 제주)",
                    },
                    "spec": {
                        "type": "string",
                        "description": "규격/등급 (선택, 예: 특, 상, 중)",
                    },
                    "min_order_qty": {
                        "type": "string",
                        "description": "최소 주문 수량 (선택)",
                    },
                    "description": {
                        "type": "string",
                        "description": "상품 상세 설명 (선택)",
                    },
                },
                "required": ["seller_id", "name", "category", "price_per_unit", "stock_quantity", "unit"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_product",
            "description": (
                "상품을 삭제한다(soft delete). deleted_at을 현재 시간으로 설정하며, "
                "실제 데이터는 보존된다. seller_id가 일치해야만 삭제 가능하다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "string",
                        "description": "삭제할 상품의 UUID",
                    },
                    "seller_id": {
                        "type": "string",
                        "description": "요청하는 판매자의 UUID (현재 로그인한 판매자 ID)",
                    },
                },
                "required": ["product_id", "seller_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_product",
            "description": (
                "상품 정보를 수정한다. 전달된 필드만 업데이트된다. "
                "seller_id가 일치해야만 수정 가능하다. "
                "수정 가능 필드: name, price_per_unit, category, origin, spec, description."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "string",
                        "description": "수정할 상품의 UUID",
                    },
                    "seller_id": {
                        "type": "string",
                        "description": "요청하는 판매자의 UUID (현재 로그인한 판매자 ID)",
                    },
                    "name": {
                        "type": "string",
                        "description": "변경할 상품명 (선택)",
                    },
                    "price_per_unit": {
                        "type": "string",
                        "description": "변경할 단위당 가격 (원, 선택)",
                    },
                    "category": {
                        "type": "string",
                        "description": "변경할 카테고리 (선택)",
                    },
                    "origin": {
                        "type": "string",
                        "description": "변경할 산지/원산지 (선택)",
                    },
                    "spec": {
                        "type": "string",
                        "description": "변경할 규격/등급 (선택)",
                    },
                    "description": {
                        "type": "string",
                        "description": "변경할 상품 설명 (선택)",
                    },
                },
                "required": ["product_id", "seller_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_orders",
            "description": (
                "사용자의 주문 목록을 조회한다. "
                "판매자는 받은 주문, 구매자는 넣은 주문이 조회된다. "
                "status로 특정 상태(예: QUOTE_REQUESTED, SHIPPING)만 필터링할 수 있다."
            ),
            "parameters": {
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
                            "필터링할 주문 상태 (선택). "
                            "QUOTE_REQUESTED / NEGOTIATING / CONFIRMED / "
                            "PREPARING / SHIPPING / COMPLETED / CANCELLED"
                        ),
                    },
                },
                "required": ["user_id", "role"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_order_detail",
            "description": (
                "특정 주문의 상세 정보와 주문 항목(품목, 수량, 단가, 소계)을 함께 조회한다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "조회할 주문의 UUID",
                    },
                },
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_order_status",
            "description": (
                "주문의 상태를 변경한다. "
                "예: 견적 수락 시 QUOTE_REQUESTED → NEGOTIATING, "
                "출하 시작 시 PREPARING → SHIPPING."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "상태를 변경할 주문의 UUID",
                    },
                    "new_status": {
                        "type": "string",
                        "description": (
                            "변경할 상태값: "
                            "QUOTE_REQUESTED / NEGOTIATING / CONFIRMED / "
                            "PREPARING / SHIPPING / COMPLETED / CANCELLED"
                        ),
                    },
                },
                "required": ["order_id", "new_status"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_order",
            "description": (
                "새 주문을 생성한다. "
                "buyer_id, seller_id, 상품 ID, 수량, 단가는 필수. "
                "주문 상태는 QUOTE_REQUESTED로 시작된다. "
                "order_items에도 자동으로 항목이 등록된다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "buyer_id": {
                        "type": "string",
                        "description": "구매자의 UUID",
                    },
                    "seller_id": {
                        "type": "string",
                        "description": "판매자의 UUID",
                    },
                    "product_id": {
                        "type": "string",
                        "description": "주문할 상품의 UUID",
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
                        "description": "납품 희망일 (선택, ISO 8601 형식: YYYY-MM-DD)",
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
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_order",
            "description": (
                "주문을 삭제한다(soft delete). deleted_at을 현재 시간으로 설정하며, "
                "buyer_id 또는 seller_id 중 하나라도 user_id와 일치하면 삭제 가능하다."
            ),
            "parameters": {
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
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_sellers_by_product",
            "description": (
                "특정 카테고리의 모든 판매자 및 상품 목록을 조회한다. "
                "구매자가 특정 품목(예: 풋사과, 청사과)을 찾을 때, 이 도구로 상위 카테고리(예: FRUIT) 전체를 조회한 후 "
                "LLM이 직접 결과값을 읽고 사용자가 원하는 세부 품목 조건에 맞는 것만 필터링해서 답변해야 한다."),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "조회할 상위 카테고리명 (예: FRUIT, VEGETABLE, GRAIN). 카테고리가 모호하거나 전체를 뒤져야 하면 'ALL'을 입력하세요.",
                    },
                },
                "required": ["category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_buyers_by_product",
            "description": (
                "특정 카테고리의 상품을 구매한 이력이 있는 바이어 전체 목록을 조회한다. "
                "조회 후 LLM이 직접 결과값을 분석하여 판매자의 특정 품목(예: 풋사과)에 관심 있을 만한 바이어를 필터링한다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "조회할 상위 카테고리명 (예: FRUIT, VEGETABLE, GRAIN). 모호하면 'ALL'을 입력하세요.",
                    },
                },
                "required": ["category"],
            },
        },
    },
]


# ─────────────────────────────────────────────
# 역할별 시스템 프롬프트
# ─────────────────────────────────────────────

AGENT_SELLER_SYSTEM = """당신은 AgriFlow 농산물 유통 플랫폼의 AI 업무 도우미입니다.

[사용자 정보]
- 역할: 판매자 (농가/도매상/유통업체)
- 회사명: {company_name}
- 담당자: {user_name}
- 사용자 ID: {user_id}

[사용 가능한 도구]
질문에 답하기 위해 필요하다면 제공된 도구를 사용하여 실시간 데이터를 조회하거나 업데이트하세요.
- 상품/재고 조회: get_products, check_stock
- 상품 등록: create_product
- 상품 수정: update_product
- 상품 삭제: delete_product
- 재고 수정: update_stock
- 주문 조회: get_orders, get_order_detail
- 주문 상태 변경: update_order_status
- 주문 삭제: delete_order

[상품 등록 안내]
사용자가 상품 등록 의사를 밝히면 아래 양식을 안내한다. 추가 정보는 처음 한 번만 알려준다.

필수 정보:
- 상품명:
- 카테고리: (FRUIT/VEGETABLE/GRAIN 중 선택)
- 단가: (원/단위)
- 재고 수량:
- 판매 단위: (kg/box/개/포대 중 선택)

추가 정보 (선택):
- 산지:
- 규격/등급:
- 최소 주문 수량:
- 상품 설명:

필수 정보 중 하나라도 누락되면 누락된 항목만 다시 요청한다. 추가 정보 양식은 반복하지 않는다.

[필수 정보 누락 처리 원칙]
tool을 실행하기 전에 필요한 정보가 부족하면 tool을 호출하지 말고 누락된 항목만 다시 요청한다.
- 재고 수정: 상품명 또는 상품 ID, 변경할 수량 필요
- 주문 상태 변경: 주문번호 또는 주문 ID, 변경할 상태 필요
- 상품 수정: 상품명 또는 상품 ID, 변경할 항목과 값 필요
- 상품 삭제: 상품명 또는 상품 ID 필요
- 주문 삭제: 주문번호 또는 주문 ID 필요
누락된 항목이 있으면 "아래 정보가 필요합니다:" 형식으로 해당 항목만 간결하게 요청한다.

[응답 원칙]
1. 반드시 한국어로 답변
2. 농산물 유통 실무 용어 사용 (출하, 납품, 단가, 도매가, 박스 등)
3. 수치는 구체적으로 (예: 3건, 45,000원/박스)
4. 긴 답변은 항목(-)으로 구분하여 읽기 쉽게
5. DB 조회 없이는 확정적인 수치를 말하지 않음
6. DB 조회 결과를 그대로 전달한다. 임의로 해석하거나 추측하지 않는다.
7. "덮어쓰기", "이미 존재하여 대체" 같은 표현 금지 — tool이 반환한 message를 그대로 전달한다.
8. 상품 목록 조회 시 실제 DB에서 가져온 개수를 정확히 말한다.
9. [스마트 필터링] 사용자가 특정 품목(예: '풋사과', '청사과')을 찾을 때, DB 검색은 카테고리 단위(예: FRUIT)로 넓게 수행하세요. DB가 반환한 전체 목록을 당신이 직접 분석하여, 사용자의 원래 의도와 일치하거나 가장 유사한 상품만 추려내어 리스트를 제공하세요."""
AGENT_BUYER_SYSTEM = """당신은 AgriFlow 농산물 유통 플랫폼의 AI 업무 도우미입니다.

[사용자 정보]
- 역할: 구매자 (마트/식자재업체/식당)
- 회사명: {company_name}
- 담당자: {user_name}
- 사용자 ID: {user_id}

[사용 가능한 도구]
질문에 답하기 위해 필요하다면 제공된 도구를 사용하여 실시간 데이터를 조회하거나 업데이트하세요.
- 주문 조회: get_orders, get_order_detail
- 주문 상태 확인 및 변경: update_order_status

[응답 원칙]
1. 반드시 한국어로 답변
2. 구매자 관점 용어 사용 (발주, 납품, 수급, 단가 비교 등)
3. 납품 일정·비용 절감 정보 우선 제공
4. 수치는 구체적으로 (예: 3건, 45,000원/박스)
5. DB 조회 없이는 확정적인 수치를 말하지 않음
6. DB 조회 결과를 그대로 전달한다. 임의로 해석하거나 추측하지 않는다.
7. "덮어쓰기", "이미 존재하여 대체" 같은 표현 금지 — tool이 반환한 message를 그대로 전달한다.
8. 상품 목록 조회 시 실제 DB에서 가져온 개수를 정확히 말한다.
9. [스마트 필터링] 사용자가 특정 품목(예: '풋사과', '청사과')을 찾을 때, DB 검색은 카테고리 단위(예: FRUIT)로 넓게 수행. DB가 반환한 전체 목록을  직접 분석하여, 사용자의 원래 의도와 일치하거나 가장 유사한 상품만 추려내어 리스트를 제공."""

# ─────────────────────────────────────────────
# 헬퍼: tool 실행
# ─────────────────────────────────────────────

def _execute_tool(tool_name: str, tool_input: dict[str, Any]) -> str:
    """
    tool 이름과 입력값으로 agent_tools.py의 실제 함수를 실행한다.
    결과는 JSON 문자열로 반환한다.
    """
    func = TOOL_FUNCTION_MAP.get(tool_name)
    if func is None:
        return json.dumps(
            {"success": False, "error": f"알 수 없는 tool: {tool_name}"},
            ensure_ascii=False,
        )
    try:
        # LLM이 integer 파라미터를 문자열로 보내는 경우 강제 변환
        INT_FIELDS = {
            "new_quantity", "price_per_unit", "stock_quantity",
            "min_order_qty", "quantity", "unit_price",
        }
        for field in INT_FIELDS:
            if field in tool_input and tool_input[field] != "" and tool_input[field] is not None:
                try:
                    tool_input[field] = int(tool_input[field])
                except (ValueError, TypeError):
                    pass
            elif field in tool_input and tool_input[field] == "":
                tool_input[field] = None

        result = func(**tool_input)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps(
            {"success": False, "error": f"tool 실행 오류: {str(e)}"},
            ensure_ascii=False,
        )


# ─────────────────────────────────────────────
# 노드 함수들
# ─────────────────────────────────────────────

async def orchestrator_node(state: AgentState) -> dict:
    """
    LLM에게 사용자 메시지를 전달하고, intent를 분류하며 필요한 tool을 선택한다.
    - tool_calls가 있으면 intent를 INVENTORY 또는 ORDER로 설정
    - tool_calls가 없으면 intent를 GENERAL로 설정하고 응답 텍스트를 final_response에 저장
    """
    client = AsyncGroq(api_key=settings.GROQ_API_KEY)
    model = "meta-llama/llama-4-scout-17b-16e-instruct"

    # 시스템 프롬프트가 messages에 아직 없으면 초기화
    # (첫 번째 호출 시에만 시스템 + 유저 메시지를 구성)
    current_messages = state["messages"]

    response = await client.chat.completions.create(
        model=model,
        messages=current_messages,
        tools=TOOLS,
        tool_choice="auto",
    )

    choice = response.choices[0]

    # tool 호출 없이 최종 답변이 나온 경우
    if choice.finish_reason == "stop":
        final_text = choice.message.content or ""
        return {
            "intent": "GENERAL",
            "final_response": final_text,
            "messages": [{"role": "assistant", "content": final_text}],
        }

    # tool 호출이 필요한 경우 — intent를 판단
    if choice.finish_reason == "tool_calls":
        tool_calls = choice.message.tool_calls

        # tool 이름 기반으로 intent 분류
        tool_names = [tc.function.name for tc in tool_calls]
        if any(t in tool_names for t in ["get_products", "check_stock", "update_stock", "create_product", "delete_product", "update_product", "find_sellers_by_product", "find_buyers_by_product"]):
            intent = "INVENTORY"
        else:
            intent = "ORDER"

        # assistant 메시지(tool_calls 포함)를 히스토리에 추가
        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": choice.message.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in tool_calls
            ],
        }

        return {
            "intent": intent,
            "messages": [assistant_msg],
            # tool_calls 정보를 tool_results에 임시 저장 (inventory_order_node에서 처리)
            "tool_results": [
                {
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                }
                for tc in tool_calls
            ],
        }

    # 예상치 못한 finish_reason
    return {
        "intent": "GENERAL",
        "final_response": "요청을 처리하는 중 문제가 발생했습니다. 다시 시도해 주세요.",
    }


async def inventory_order_node(state: AgentState) -> dict:
    """
    orchestrator_node가 선택한 tool들을 실제로 실행한다.
    tool 결과를 messages에 추가하고, tools_used 목록을 업데이트한다.
    """
    pending_tools = state.get("tool_results", [])
    tools_used = list(state.get("tools_used", []))
    new_messages: list[dict[str, Any]] = []

    for tool_call in pending_tools:
        tool_name = tool_call["name"]
        tool_input = json.loads(tool_call["arguments"])

        # 사용된 tool 이름 기록 (중복 제거)
        if tool_name not in tools_used:
            tools_used.append(tool_name)

        # 실제 tool 함수 실행
        result_content = _execute_tool(tool_name, tool_input)

        # OpenAI/Groq 스타일: role="tool" + tool_call_id
        new_messages.append({
            "role": "tool",
            "tool_call_id": tool_call["id"],
            "content": result_content,
        })

    return {
        "messages": new_messages,
        "tools_used": tools_used,
        "tool_results": [],  # 처리 완료 후 초기화
        "tool_round": state.get("tool_round", 0) + 1,
    }


async def response_node(state: AgentState) -> dict:
    """
    tool 결과들을 바탕으로 LLM에게 최종 답변을 생성하도록 요청한다.
    이미 final_response가 있으면 (GENERAL intent) 그대로 반환한다.
    """
    # orchestrator_node에서 tool 없이 바로 답변이 나온 경우
    if state.get("final_response"):
        return {}

    client = AsyncGroq(api_key=settings.GROQ_API_KEY)
    model = "meta-llama/llama-4-scout-17b-16e-instruct"

    response = await client.chat.completions.create(
        model=model,
        messages=state["messages"],
        tools=TOOLS,
        tool_choice="none",  # 최종 답변 생성 단계에서는 tool 사용 금지
    )

    final_text = response.choices[0].message.content or "처리 결과를 정리하는 중 오류가 발생했습니다."
    return {"final_response": final_text}


# ─────────────────────────────────────────────
# 라우팅 함수들
# ─────────────────────────────────────────────

def route_after_orchestrator(state: AgentState) -> str:
    """
    orchestrator_node 실행 후 다음 노드를 결정한다.
    - tool 실행이 필요하면 inventory_order_node
    - 바로 답변 가능하면 response_node
    """
    if state["intent"] in ["INVENTORY", "ORDER"]:
        return "inventory_order_node"
    return "response_node"


def route_after_tool(state: AgentState) -> str:
    """
    inventory_order_node 실행 후 다음 노드를 결정한다.
    - tool_round가 최대(5)에 도달했으면 response_node로 강제 이동
    - 추가 tool 실행이 필요하면 orchestrator_node로 복귀
    - 완료되면 response_node
    """
    MAX_TOOL_ROUNDS = 5

    if state.get("tool_round", 0) >= MAX_TOOL_ROUNDS:
        return "response_node"

    # tool_results가 남아있으면 더 처리할 tool이 있다는 의미
    # (현재 구현에서는 inventory_order_node에서 tool_results를 비우므로
    #  orchestrator가 새로운 tool_calls를 만들면 다시 채워진다)
    # 기본적으로는 response_node로 이동하되,
    # 모델이 추가 tool을 요청할 수도 있으므로 orchestrator로 한 번 더 보낸다.
    # 단, 이미 tools_used가 있으면 충분히 처리된 것으로 판단
    if state.get("tools_used"):
        return "response_node"

    return "orchestrator_node"


# ─────────────────────────────────────────────
# 그래프 조립
# ─────────────────────────────────────────────

def _build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("orchestrator_node", orchestrator_node)
    graph.add_node("inventory_order_node", inventory_order_node)
    graph.add_node("response_node", response_node)

    graph.set_entry_point("orchestrator_node")

    graph.add_conditional_edges(
        "orchestrator_node",
        route_after_orchestrator,
        {
            "inventory_order_node": "inventory_order_node",
            "response_node": "response_node",
        },
    )
    graph.add_conditional_edges(
        "inventory_order_node",
        route_after_tool,
        {
            "orchestrator_node": "orchestrator_node",
            "response_node": "response_node",
        },
    )
    graph.add_edge("response_node", END)

    return graph.compile()


_compiled_graph = _build_graph()


# ─────────────────────────────────────────────
# AgentOrchestrator — ai_assistant.py와의 인터페이스 유지
# ─────────────────────────────────────────────

class AgentOrchestrator:
    """
    LangGraph StateGraph 기반 오케스트레이터.
    ai_assistant.py가 호출하는 run() 인터페이스를 유지한다.
    """

    async def run(
        self,
        user_message: str,
        user_id: str,
        role: str,
        user_info: dict,
        history: list = [],
    ) -> dict:
        """
        오케스트레이터 메인 실행 메서드.

        Args:
            user_message: 사용자가 입력한 질문/요청
            user_id: 현재 로그인한 사용자 UUID
            role: 사용자 역할 (SELLER 또는 BUYER)
            user_info: 사용자 정보 dict (name, company_name 포함)

        Returns:
            {
                "response": "모델의 최종 텍스트 답변",
                "tools_used": ["실행된 tool 이름 목록"]
            }
        """
        company_name = user_info.get("company_name", "미설정")
        user_name = user_info.get("name", "사용자")

        # 역할에 따라 시스템 프롬프트 선택
        if role == "SELLER":
            system_prompt = AGENT_SELLER_SYSTEM.format(
                company_name=company_name,
                user_name=user_name,
                user_id=user_id,
            )
        else:
            system_prompt = AGENT_BUYER_SYSTEM.format(
                company_name=company_name,
                user_name=user_name,
                user_id=user_id,
            )

        # 초기 상태 구성
        # messages에 system + user 메시지를 포함시켜 시작
        initial_state: AgentState = {
            "user_id": user_id,
            "user_role": role,
            "user_info": user_info,
            "message": user_message,
            "intent": "GENERAL",
            "messages": [
                {"role": "system", "content": system_prompt},
                *history,  # 이전 대화 삽입
                {"role": "user", "content": user_message},
            ],
            "tool_results": [],
            "tools_used": [],
            "final_response": "",
            "tool_round": 0,
        }

        # LangGraph 실행
        try:
            final_state = await _compiled_graph.ainvoke(initial_state)
            return {
                "response": final_state.get("final_response") or "응답을 생성하지 못했습니다.",
                "tools_used": final_state.get("tools_used", []),
            }
        except Exception as e:
            return {
                "response": f"요청을 처리하는 중 오류가 발생했습니다: {str(e)}",
                "tools_used": [],
            }


# 싱글턴 인스턴스 — 앱 전체에서 하나만 사용
agent_orchestrator = AgentOrchestrator()
