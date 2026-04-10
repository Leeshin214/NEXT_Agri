"""
orchestrator.py — LangGraph StateGraph 기반 오케스트레이터 (TEA 방식)

동작 흐름 (AgentOrchestra 논문 방식):
  1. orchestrator_node: tools 없이 순수 LLM으로 intent만 분류 (INVENTORY / ORDER / GENERAL)
  2. inventory_order_node: 자체 LLM + TOOLS를 보유하여 직접 tool 선택·실행·반복 (최대 3회)
  3. response_node: tool 결과를 바탕으로 최종 답변 생성

라우팅:
  - orchestrator_node 후: INVENTORY/ORDER → inventory_order_node, GENERAL → response_node
  - inventory_order_node 후: response_node (자체 루프 완료 후)
"""

import json
import operator
from typing import Any, Annotated

from openai import AsyncOpenAI
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
    validation_status: str   # PASSED / RETRY / FAILED
    manual_review: bool      # 검증 실패로 수동 검토 필요 여부


# ─────────────────────────────────────────────
# inventory_order_node가 보유하는 TOOLS 목록
# (orchestrator_node는 tools 미보유)
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
                        "description": "필터링할 카테고리명 (선택). 없으면 전체 조회. 허용값: FRUIT, VEGETABLE, GRAIN, MUSHROOM, SEAFOOD, MEAT, DAIRY, HERB, LEGUME, ROOT, LEAF, PROCESSED, OTHER. 사용자가 어떤 표현을 써도 가장 가까운 카테고리로 자동 변환할 것.",
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
                    "seller_id": {
                        "type": "string",
                        "description": "판매자 UUID. product_name으로 검색할 때 범위를 좁히기 위해 사용",
                    },
                    "product_name": {
                        "type": "string",
                        "description": "조회할 상품명. product_id 모를 때 사용",
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
                    "seller_id": {
                        "type": "string",
                        "description": "판매자 UUID. product_name으로 검색할 때 범위를 좁히기 위해 사용",
                    },
                    "product_name": {
                        "type": "string",
                        "description": "재고를 수정할 상품명. product_id 모를 때 사용",
                    },
                },
                "required": ["new_quantity"],
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
                        "description": "허용값: FRUIT, VEGETABLE, GRAIN, MUSHROOM, SEAFOOD, MEAT, DAIRY, HERB, LEGUME, ROOT, LEAF, PROCESSED, OTHER. 사용자가 어떤 표현을 써도 가장 가까운 카테고리로 자동 변환할 것.",
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
                        "description": "판매 단위 (예: kg, box, piece, bag, 개, 포대, 묶음, g, L, ml, 판, 줄, 세트)",
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
                        "description": "삭제할 상품의 UUID. 모르면 빈 문자열로 전달.",
                    },
                    "seller_id": {
                        "type": "string",
                        "description": "요청하는 판매자의 UUID (현재 로그인한 판매자 ID)",
                    },
                    "name": {
                        "type": "string",
                        "description": "삭제할 상품명. product_id를 모를 때 이름으로 검색.",
                    },
                },
                "required": ["seller_id"],
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
                        "description": "수정할 상품의 UUID. 모르면 빈 문자열로 전달.",
                    },
                    "seller_id": {
                        "type": "string",
                        "description": "요청하는 판매자의 UUID (현재 로그인한 판매자 ID)",
                    },
                    "product_name": {
                        "type": "string",
                        "description": "수정할 상품명 (product_id 모를 때 사용)",
                    },
                    "name": {
                        "type": "string",
                        "description": "변경할 상품명 (선택, 이름 자체를 바꿀 때 사용)",
                    },
                    "price_per_unit": {
                        "type": "string",
                        "description": "변경할 단위당 가격 (원, 선택)",
                    },
                    "category": {
                        "type": "string",
                        "description": "변경할 카테고리 (선택). 허용값: FRUIT, VEGETABLE, GRAIN, MUSHROOM, SEAFOOD, MEAT, DAIRY, HERB, LEGUME, ROOT, LEAF, PROCESSED, OTHER. 사용자가 어떤 표현을 써도 가장 가까운 카테고리로 자동 변환할 것.",
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
                "required": ["seller_id"],
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
                "LLM이 직접 결과값을 읽고 사용자가 원하는 세부 품목 조건에 맞는 것만 필터링해서 답변해야 한다. "
                "정확한 상품명을 알고 있는 경우 product_name을 함께 전달하면 더 정확한 결과를 반환한다."),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "조회할 상위 카테고리명. 허용값: FRUIT, VEGETABLE, GRAIN, MUSHROOM, SEAFOOD, MEAT, DAIRY, HERB, LEGUME, ROOT, LEAF, PROCESSED, OTHER. 사용자가 어떤 표현을 써도 가장 가까운 카테고리로 자동 변환할 것. 카테고리가 모호하거나 전체를 뒤져야 하면 'ALL'을 입력하세요.",
                    },
                    "product_name": {
                        "type": "string",
                        "description": "검색할 상품명 (선택). 예: 당근, 사과. 특정 상품을 찾을 때 입력하면 정확한 결과를 반환한다.",
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
                        "description": "조회할 상위 카테고리명. 허용값: FRUIT, VEGETABLE, GRAIN, MUSHROOM, SEAFOOD, MEAT, DAIRY, HERB, LEGUME, ROOT, LEAF, PROCESSED, OTHER. 사용자가 어떤 표현을 써도 가장 가까운 카테고리로 자동 변환할 것. 모호하면 'ALL'을 입력하세요.",
                    },
                },
                "required": ["category"],
            },
        },
    },
]


# ─────────────────────────────────────────────
# orchestrator_node 전용 라우터 프롬프트
# ─────────────────────────────────────────────

ORCHESTRATOR_ROUTER_SYSTEM = """당신은 AgriFlow 농산물 유통 플랫폼의 요청 라우터입니다.

사용자 메시지를 분석하여 아래 세 가지 intent 중 하나로 분류하고, 반드시 JSON 형식으로만 응답하십시오. 다른 텍스트는 절대 포함하지 마십시오.

[분류 기준]
- INVENTORY: 상품, 재고, 품목 관련 모든 요청
  예시: "사과 있어?", "사과 사고싶어", "딸기 구매하고 싶어", "어떤 과일 파는지 보여줘",
        "재고 확인해줘", "상품 등록", "상품 수정/삭제", "판매자 찾아줘", "공급처 찾아줘"
  → 특정 품목을 사거나 찾거나 확인하려는 의도가 조금이라도 있으면 무조건 INVENTORY
- ORDER: 주문, 견적, 발주, 납품 관련 요청 (주문 조회, 상태 변경, 주문 생성/삭제 등)
  예시: "주문 넣어줘", "발주 확인해줘", "납품 일정", "주문 취소"
- GENERAL: 인사, 날씨, 농산물 시세 일반 질문 등 INVENTORY/ORDER와 완전히 무관한 경우만
  예시: "안녕", "오늘 날씨", "AgriFlow가 뭐야"
  → 품목명이 하나라도 언급되면 GENERAL이 아닌 INVENTORY로 분류할 것

[응답 형식]
INVENTORY 또는 ORDER인 경우:
{"intent": "INVENTORY"}
{"intent": "ORDER"}

GENERAL인 경우 (직접 답변 포함):
{"intent": "GENERAL", "response": "한국어로 작성된 답변 내용"}

[주의사항]
- tool을 직접 호출하지 않는다. intent 분류와 GENERAL 답변만 담당한다.
- JSON 외의 텍스트, 마크다운 코드블록, 설명 문구를 절대 출력하지 않는다.
- GENERAL 답변은 농산물 유통 업무 맥락에 맞게 한국어로 작성한다."""


# ─────────────────────────────────────────────
# inventory_order_node 전용 시스템 프롬프트 (역할별)
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
사용자가 상품명, 카테고리, 단가, 재고수량, 단위를 모두 제공하면 즉시 create_product를 호출한다. 하나라도 빠지면 빠진 항목만 요청한다. 이전 대화 데이터를 임의로 재사용하지 않는다.

필수 정보:
- 상품명:
- 카테고리: (아래 중 선택, 애매하면 OTHER)
  FRUIT(과일류), VEGETABLE(채소·엽채류), GRAIN(곡물·쌀·잡곡),
  MUSHROOM(버섯류), SEAFOOD(수산물·어패류), MEAT(육류·가금류),
  DAIRY(유제품·달걀), HERB(허브·약초·향신료), LEGUME(콩류·두류),
  ROOT(뿌리채소·구근류), LEAF(잎채소·쌈채소), PROCESSED(가공식품), OTHER(기타)
- 단가: (원/단위)
- 재고 수량:
- 판매 단위: (kg / box / 개 / 포대)

추가 정보 (선택 — 원하는 항목만 입력):
- 산지:
- 규격/등급:
- 최소 주문 수량:
- 상품 설명:

필수 정보 중 하나라도 누락되면 누락된 항목만 다시 요청한다. 추가 정보 양식은 반복하지 않는다.

[판매 의도 처리 원칙]
판매자가 "~팔고싶어", "~팔려고", "~구매자 찾아줘", "~살 사람 있어?" 등의 표현을 쓰면
→ 주문 생성이 아니라 find_buyers_by_product를 호출해서 잠재 구매자를 찾아준다.
→ 결과를 아래 형식으로 출력한다:
  - 구매자명 / 거래 횟수: N회 / 주요 품목: 카테고리명
→ 구매자가 없으면 "현재 해당 품목을 구매한 이력이 있는 구매자가 없습니다"라고 안내한다.
→ 절대로 주문 생성(create_order) 흐름으로 연결하지 않는다.

[의도 구분 원칙]
- "재고 등록", "상품 등록", "신상품 추가" → create_product 흐름 (위 [상품 등록 안내] 양식 사용)
- "재고 수정", "재고 변경", "재고 조정" → update_stock 흐름 (기존 상품의 수량 변경)
- "재고 등록"을 절대로 update_stock으로 처리하지 않는다.

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
9. [스마트 필터링] 사용자가 특정 품목(예: '풋사과', '청사과')을 찾을 때, DB 검색은 카테고리 단위(예: FRUIT)로 넓게 수행하세요. DB가 반환한 전체 목록을 당신이 직접 분석하여, 사용자의 원래 의도와 일치하거나 가장 유사한 상품만 추려내어 리스트를 제공하세요.
10. 등록/수정/삭제 요청은 항상 tool을 호출해서 처리한다. tool 결과를 받기 전에 성공/실패를 말하지 않는다.
11. [절대 규칙] product_name 파라미터에 사용자가 말한 상품명을 넣을 때, 철자를 절대 바꾸지 마라. 사용자가 "새우"라고 했으면 정확히 "새우"를 넣어야 한다. 한 글자도 바꾸지 말 것."""

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
- 판매자/상품 검색: find_sellers_by_product

[상품/판매자 검색 원칙]
사용자가 특정 품목을 사고 싶거나 공급처를 찾을 때 반드시 find_sellers_by_product를 호출한다.
호출 후 반환된 판매자 목록을 아래 형식으로 리스트 출력한다:
- 판매자명: {seller_name} ({seller_company}) / 상품명: {name} / 재고: {stock_quantity}{unit} / 단가: {price_per_unit}원/{unit}
DB 결과가 없으면 "현재 조건에 맞는 판매자가 없습니다"라고 안내한다.
절대로 tool 호출 없이 "공급처를 찾아보세요"류의 안내만 하지 않는다.

[응답 원칙]
1. 반드시 한국어로 답변
2. 구매자 관점 용어 사용 (발주, 납품, 수급, 단가 비교 등)
3. 납품 일정·비용 절감 정보 우선 제공
4. 수치는 구체적으로 (예: 3건, 45,000원/박스)
5. DB 조회 없이는 확정적인 수치를 말하지 않음
6. DB 조회 결과를 그대로 전달한다. 임의로 해석하거나 추측하지 않는다.
7. "덮어쓰기", "이미 존재하여 대체" 같은 표현 금지 — tool이 반환한 message를 그대로 전달한다.
8. 상품 목록 조회 시 실제 DB에서 가져온 개수를 정확히 말한다.
9. [스마트 필터링] 사용자가 특정 품목(예: '풋사과', '청사과')을 찾을 때, DB 검색은 카테고리 단위(예: FRUIT)로 넓게 수행. DB가 반환한 전체 목록을 직접 분석하여, 사용자의 원래 의도와 일치하거나 가장 유사한 상품만 추려내어 리스트를 제공.
10. 등록/수정/삭제 요청은 항상 tool을 호출해서 처리한다. tool 결과를 받기 전에 성공/실패를 말하지 않는다.
11. [절대 규칙] product_name 파라미터에 사용자가 말한 상품명을 넣을 때, 철자를 절대 바꾸지 마라. 사용자가 "새우"라고 했으면 정확히 "새우"를 넣어야 한다. 한 글자도 바꾸지 말 것."""


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
# 헬퍼: UUID 유효성 검증 및 자동 교정
# ─────────────────────────────────────────────

import inspect as _inspect
import re as _re

_UUID_RE = _re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    _re.I,
)


def _fix_id_params(tool_name: str, tool_input: dict[str, Any], user_id: str) -> dict[str, Any]:
    """
    LLM이 id 파라미터를 null이거나 UUID가 아닌 값으로 보낸 경우 user_id로 자동 교체한다.
    """
    func = TOOL_FUNCTION_MAP.get(tool_name)
    if func is None:
        return tool_input
    params = set(_inspect.signature(func).parameters.keys())
    for id_field in ("seller_id", "user_id", "buyer_id"):
        if id_field in params:
            val = tool_input.get(id_field)
            if not val or not _UUID_RE.match(str(val)):
                tool_input[id_field] = user_id
    return tool_input


# ─────────────────────────────────────────────
# 노드 함수들
# ─────────────────────────────────────────────

async def orchestrator_node(state: AgentState) -> dict:
    """
    TEA 방식 라우터 노드.
    - tools 파라미터 없이 순수 LLM 호출
    - JSON 응답으로 intent만 분류 (INVENTORY / ORDER / GENERAL)
    - GENERAL인 경우 직접 답변 텍스트도 반환
    - tool을 직접 선택하거나 실행하지 않는다
    """
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    model = "gpt-4o-mini"

    current_messages = state["messages"]

    response = await client.chat.completions.create(
        model=model,
        messages=current_messages,
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content or "{}"

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = {"intent": "GENERAL", "response": content}

    intent = parsed.get("intent", "GENERAL").upper()
    if intent not in ("INVENTORY", "ORDER", "GENERAL"):
        intent = "GENERAL"

    if intent == "GENERAL":
        answer = parsed.get("response", "")
        return {
            "intent": "GENERAL",
            "final_response": answer,
            "messages": [{"role": "assistant", "content": answer}],
        }

    # INVENTORY 또는 ORDER — inventory_order_node로 라우팅 (라우터 JSON은 messages에 추가하지 않음)
    return {
        "intent": intent,
    }


async def inventory_order_node(state: AgentState) -> dict:
    """
    TEA 방식 전문 에이전트 노드.
    - 자체 LLM + TOOLS를 보유하여 직접 tool 선택·실행
    - 최대 MAX_TOOL_ROUNDS(3)회 루프로 추가 tool 호출 처리
    - 완료 후 tool_results에 결과 저장, response_node로 이동
    """
    MAX_TOOL_ROUNDS = 3

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    model = "gpt-4o-mini"

    user_id = state.get("user_id", "")
    user_role = state.get("user_role", "SELLER")
    user_info = state.get("user_info", {})
    company_name = user_info.get("company_name", "미설정")
    user_name = user_info.get("name", "사용자")

    # 역할별 시스템 프롬프트
    if user_role == "SELLER":
        agent_system = AGENT_SELLER_SYSTEM.format(
            company_name=company_name,
            user_name=user_name,
            user_id=user_id,
        )
    else:
        agent_system = AGENT_BUYER_SYSTEM.format(
            company_name=company_name,
            user_name=user_name,
            user_id=user_id,
        )

    # inventory_order_node 전용 메시지 구성
    # 원래 user 메시지를 추출하여 새 대화로 시작
    original_user_message = state.get("message", "")
    history_messages = [
        m for m in state.get("messages", [])
        if m.get("role") in ("user", "assistant")
        and m.get("content") not in (None, "")
        and not (m.get("role") == "assistant" and _is_router_json(m.get("content", "")))
    ]

    # 시스템 + 히스토리(user/assistant만) + 현재 user 메시지
    agent_messages: list[dict[str, Any]] = [
        {"role": "system", "content": agent_system},
    ]
    # 이전 대화 중 실제 user/assistant 교환만 포함 (현재 메시지 제외)
    for m in history_messages:
        if m.get("content") != original_user_message:
            agent_messages.append(m)
    agent_messages.append({"role": "user", "content": original_user_message})

    tools_used: list[str] = list(state.get("tools_used", []))
    all_tool_results: list[dict[str, Any]] = []
    new_messages: list[dict[str, Any]] = []

    try:
        for round_idx in range(MAX_TOOL_ROUNDS):
            response = await client.chat.completions.create(
                model=model,
                messages=agent_messages,
                tools=TOOLS,
                tool_choice="auto",
            )

            choice = response.choices[0]

            if choice.finish_reason == "stop":
                # tool 호출 없이 답변 완료
                final_text = choice.message.content or ""
                new_messages.append({"role": "assistant", "content": final_text})
                # tool_results가 있으면 response_node가 요약, 없으면 직접 final_response 설정
                if not all_tool_results:
                    return {
                        "messages": new_messages,
                        "tools_used": tools_used,
                        "tool_results": all_tool_results,
                        "tool_round": state.get("tool_round", 0) + round_idx + 1,
                        "final_response": final_text,
                    }
                break

            if choice.finish_reason == "tool_calls":
                tool_calls = choice.message.tool_calls or []

                # assistant 메시지(tool_calls 포함)를 agent_messages에 추가
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
                agent_messages.append(assistant_msg)
                new_messages.append(assistant_msg)

                # 각 tool 실행
                for tc in tool_calls:
                    tool_name = tc.function.name
                    try:
                        tool_input = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        tool_input = {}

                    # UUID 파라미터 자동 교정
                    tool_input = _fix_id_params(tool_name, tool_input, user_id)

                    # tool 이름 기록
                    if tool_name not in tools_used:
                        tools_used.append(tool_name)

                    # tool 실행
                    result_content = _execute_tool(tool_name, tool_input)

                    tool_msg: dict[str, Any] = {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_content,
                    }
                    agent_messages.append(tool_msg)
                    new_messages.append(tool_msg)

                    # 결과 누적
                    try:
                        parsed_result = json.loads(result_content)
                    except json.JSONDecodeError:
                        parsed_result = {"raw": result_content}
                    all_tool_results.append({
                        "tool_name": tool_name,
                        "result": parsed_result,
                    })

                # 마지막 라운드면 루프 종료
                if round_idx == MAX_TOOL_ROUNDS - 1:
                    break
                # 다음 라운드로 계속
                continue

            # 예상치 못한 finish_reason
            break

    except Exception as e:
        return {
            "messages": [],
            "tools_used": [],
            "tool_results": [],
            "tool_round": state.get("tool_round", 0) + 1,
            "final_response": f"요청을 처리하는 중 오류가 발생했습니다: {str(e)}",
        }

    return {
        "messages": new_messages,
        "tools_used": tools_used,
        "tool_results": all_tool_results,
        "tool_round": state.get("tool_round", 0) + MAX_TOOL_ROUNDS,
    }


def _is_router_json(content: str) -> bool:
    """orchestrator_node가 생성한 라우터 JSON인지 판단한다."""
    try:
        parsed = json.loads(content.strip())
        if isinstance(parsed, dict) and "intent" in parsed:
            return True
    except (json.JSONDecodeError, AttributeError):
        pass
    return False


async def validator_node(state: AgentState) -> dict:
    """
    TEA 방식 검증 노드.
    - tool_results를 검사하여 PASSED / RETRY / FAILED 판정
    - PASSED: response_node로 이동
    - RETRY (tool_round < 2): inventory_order_node로 재시도
    - FAILED (tool_round >= 2): response_node로 이동 + manual_review=True
    """
    tool_results = state.get("tool_results", [])
    tool_round = state.get("tool_round", 0)

    # tool을 사용하지 않은 경우 → PASSED
    if not tool_results:
        return {"validation_status": "PASSED"}

    # 마지막 tool 결과 확인
    last_result = tool_results[-1] if tool_results else {}
    result_data = last_result.get("result", {})

    # success: false인 경우 실패로 판단
    if isinstance(result_data, dict) and result_data.get("success") is False:
        if tool_round < 2:
            return {"validation_status": "RETRY"}
        else:
            return {"validation_status": "FAILED", "manual_review": True}

    return {"validation_status": "PASSED"}


async def response_node(state: AgentState) -> dict:
    """
    tool 결과들을 바탕으로 LLM에게 최종 답변을 생성하도록 요청한다.
    이미 final_response가 있으면 (GENERAL intent 또는 inventory_order_node 직접 답변) 그대로 반환한다.
    """
    # orchestrator_node 또는 inventory_order_node에서 이미 답변이 생성된 경우
    if state.get("final_response"):
        return {}

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    model = "gpt-4o-mini"

    import json as _json

    # tool 결과 메시지 파싱
    tool_results_parsed: list[Any] = []
    tool_results_text = ""
    for msg in state["messages"]:
        if msg.get("role") == "tool":
            content = msg.get("content", "")
            tool_results_text += content + "\n"
            try:
                tool_results_parsed.append(_json.loads(content))
            except Exception:
                pass

    # tool 결과에서 직접 message/error 추출 가능하면 LLM 없이 바로 반환
    if tool_results_parsed:
        last = tool_results_parsed[-1]
        if isinstance(last, dict):
            if last.get("message"):
                return {"final_response": last["message"]}
            if not last.get("success") and last.get("error"):
                return {"final_response": f"처리 중 오류가 발생했습니다: {last['error']}"}

    # 직접 추출 불가능한 경우만 LLM으로 요약
    # response_node는 라우터 프롬프트가 아닌 역할별 에이전트 프롬프트를 사용
    user_role = state.get("user_role", "SELLER")
    user_info = state.get("user_info", {})
    user_id = state.get("user_id", "")
    if user_role == "SELLER":
        agent_sys = AGENT_SELLER_SYSTEM.format(
            company_name=user_info.get("company_name", "미설정"),
            user_name=user_info.get("name", "사용자"),
            user_id=user_id,
        )
    else:
        agent_sys = AGENT_BUYER_SYSTEM.format(
            company_name=user_info.get("company_name", "미설정"),
            user_name=user_info.get("name", "사용자"),
            user_id=user_id,
        )
    system_msg = {"role": "system", "content": agent_sys}

    summary_messages = [
        system_msg,
        {
            "role": "user",
            "content": (
                f"다음 tool 실행 결과를 보고 사용자에게 한국어로 자연스럽게 답변해줘. "
                f"JSON이나 코드 블록 형식으로 출력하지 말고 일반 텍스트로만 답변해.\n\n"
                f"tool 결과:\n{tool_results_text}\n\n"
                f"원래 사용자 요청: {state['message']}"
            ),
        },
    ]

    response = await client.chat.completions.create(
        model=model,
        messages=summary_messages,
    )

    final_text = response.choices[0].message.content or "처리 결과를 정리하는 중 오류가 발생했습니다."

    # 그래도 JSON이 나오면 message/error 직접 추출
    try:
        parsed = _json.loads(final_text.strip())
        if isinstance(parsed, dict):
            final_text = parsed.get("message") or parsed.get("error") or str(parsed)
    except Exception:
        pass

    return {"final_response": final_text}


# ─────────────────────────────────────────────
# 라우팅 함수들
# ─────────────────────────────────────────────

def route_after_orchestrator(state: AgentState) -> str:
    """
    orchestrator_node 실행 후 다음 노드를 결정한다.
    - INVENTORY 또는 ORDER → inventory_order_node (전문 에이전트)
    - GENERAL → response_node (orchestrator가 직접 답변 완료)
    """
    if state["intent"] in ("INVENTORY", "ORDER"):
        return "inventory_order_node"
    return "response_node"


def route_after_validator(state: AgentState) -> str:
    """
    validator_node 실행 후 다음 노드를 결정한다.
    - RETRY → inventory_order_node (재시도)
    - PASSED / FAILED → response_node
    """
    status = state.get("validation_status", "PASSED")
    if status == "RETRY":
        return "inventory_order_node"
    return "response_node"


# ─────────────────────────────────────────────
# 그래프 조립
# ─────────────────────────────────────────────

def _build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("orchestrator_node", orchestrator_node)
    graph.add_node("inventory_order_node", inventory_order_node)
    graph.add_node("validator_node", validator_node)
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
    graph.add_edge("inventory_order_node", "validator_node")
    graph.add_conditional_edges(
        "validator_node",
        route_after_validator,
        {
            "inventory_order_node": "inventory_order_node",
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
    LangGraph StateGraph 기반 오케스트레이터 (TEA 방식).
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
            history: 이전 대화 메시지 목록

        Returns:
            {
                "response": "모델의 최종 텍스트 답변",
                "tools_used": ["실행된 tool 이름 목록"]
            }
        """
        # orchestrator_node는 라우터 전용 시스템 프롬프트 사용
        initial_state: AgentState = {
            "user_id": user_id,
            "user_role": role,
            "user_info": user_info,
            "message": user_message,
            "intent": "GENERAL",
            "messages": [
                {"role": "system", "content": ORCHESTRATOR_ROUTER_SYSTEM},
                *[m for m in history if m.get("role") in ("user", "assistant")],
                {"role": "user", "content": user_message},
            ],
            "tool_results": [],
            "tools_used": [],
            "final_response": "",
            "tool_round": 0,
            "validation_status": "",
            "manual_review": False,
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