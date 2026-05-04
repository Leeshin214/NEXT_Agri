"""
orchestrator.py — LangGraph StateGraph 기반 오케스트레이터 (TEA 방식)

동작 흐름 (AgentOrchestra 논문 방식):
  1. orchestrator_node: tools 없이 순수 LLM으로 intent만 분류
     (INVENTORY / ORDER / CALENDAR / GENERAL)
     CALENDAR 는 subtype(DATA/REASON) + target_year/month 도 함께 추출
  2. inventory_order_node: 자체 LLM + TOOLS 보유, tool 선택·실행 (최대 3회)
  3. calendar_data_node: 캘린더 조회/등록 두 tool 만 노출 (최대 2회 루프)
  4. calendar_reason_node: schedule_agent.get_recommendation 으로 추천 후 자연어화
  5. response_node: tool 결과를 바탕으로 최종 답변 생성

라우팅:
  - orchestrator_node 후:
      INVENTORY/ORDER → inventory_order_node
      CALENDAR + DATA → calendar_data_node
      CALENDAR + REASON → calendar_reason_node
      GENERAL → response_node
  - inventory_order_node 후: validator_node → response_node
  - calendar_data_node / calendar_reason_node 후: response_node 직행

프롬프트 구조 (REFACTOR 1):
  AGENT_BASE_SYSTEM (공통 12 case·권한·응답 원칙·일정 등록 원칙·모호성 처리)
  + SELLER_ROLE_APPENDIX (판매자 전용 도구·등록 원칙)
  + BUYER_ROLE_APPENDIX (구매자 전용 도구·검색 원칙)
  + FEW_SHOT_EXAMPLES
  → AGENT_SELLER_SYSTEM, AGENT_BUYER_SYSTEM 으로 합성
"""

import json
import operator
from datetime import datetime
from typing import Any, Annotated

from langgraph.graph import StateGraph, END
from typing import TypedDict, Optional

from app.core.llm import get_openai_client
from app.services.agent_tools import TOOL_FUNCTION_MAP
from app.services.schedule_agent import schedule_agent


# ─────────────────────────────────────────────
# AgentState 정의
# ─────────────────────────────────────────────

class AgentState(TypedDict):
    user_id: str
    user_role: str           # SELLER / BUYER
    user_info: dict          # name, company_name
    message: str             # 사용자 입력
    intent: str              # INVENTORY / ORDER / CALENDAR / GENERAL
    subtype: str             # CALENDAR 분기에서 DATA / REASON, 그 외엔 ""
    target_year: int         # CALENDAR 분기에서만 사용, 기본 0
    target_month: int        # CALENDAR 분기에서만 사용, 기본 0
    history: list            # 순수 user/assistant 대화 히스토리 (DB에서 가져온 깨끗한 데이터)
    messages: Annotated[list, operator.add]  # 라우터 전용 메시지 (system + history + 현재 user)
    tool_results: list       # 실행된 tool 결과들
    tools_used: list         # 사용된 tool 이름들
    final_response: str      # 최종 답변
    tool_round: int          # tool 실행 라운드 카운터 (무한루프 방지)
    validation_status: str   # PASSED / RETRY / FAILED
    manual_review: bool      # 검증 실패로 수동 검토 필요 여부
    order_id: Optional[str]  # 현재 채팅방 컨텍스트 — 협상/납품일 변경 도구의 기본 order_id
    room_id: Optional[str]   # 현재 채팅방 ID


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
                "수정 가능 필드: name, price_per_unit, category, origin, spec, description. "
                "중요: product_id를 몰라도 product_name에 상품명을 넣으면 agent_tools.update_product가 해당 판매자의 상품을 이름으로 찾아 수정한다. "
                "따라서 '감자 단가 2700원으로 바꿔줘'처럼 상품명과 변경값이 있으면 확인 질문 없이 즉시 update_product를 호출하라."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "string",
                        "description": "수정할 상품의 UUID. 모르면 빈 문자열로 전달하고 product_name을 반드시 사용한다.",
                    },
                    "seller_id": {
                        "type": "string",
                        "description": "요청하는 판매자의 UUID (현재 로그인한 판매자 ID)",
                    },
                    "product_name": {
                        "type": "string",
                        "description": "수정할 상품명. product_id를 모를 때 반드시 사용한다. 예: 감자, 옥수수",
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
                "사용자의 주문 목록을 조회한다 (삭제된 주문은 제외 — soft delete 자동 필터). "
                "판매자는 받은 주문, 구매자는 넣은 주문이 조회된다. "
                "단일 상태 필터는 status, 다중 상태 필터는 status_in 을 사용한다 (status_in 이 우선). "
                "사용자가 '진행 중인 주문', '활성 주문', '내 주문' 처럼 진행 상태 전체를 물어보면 "
                "반드시 status_in=['QUOTE_REQUESTED','NEGOTIATING','CONFIRMED','PREPARING','SHIPPING'] "
                "로 호출하라 — 완료(COMPLETED)/취소(CANCELLED) 는 자동 제외된다. "
                "단일 상태(예: '배송 중인 주문', '견적 요청만') 만 묻는 경우엔 status='SHIPPING' 처럼 단일 값 사용. "
                "주의: 사용자가 '거래요청 들어온거 있어?', '새로운 거래' 등을 물어보면 "
                "이것은 새로운 주문/견적 요청을 의미하므로 반드시 이 도구를 호출하여 확인하라."
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
                            "필터링할 단일 주문 상태 (선택, 하위호환). "
                            "QUOTE_REQUESTED / NEGOTIATING / CONFIRMED / "
                            "PREPARING / SHIPPING / COMPLETED / CANCELLED. "
                            "status_in 과 동시 지정 시 status_in 이 우선."
                        ),
                    },
                    "status_in": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "QUOTE_REQUESTED", "NEGOTIATING", "CONFIRMED",
                                "PREPARING", "SHIPPING", "COMPLETED", "CANCELLED",
                            ],
                        },
                        "description": (
                            "다중 상태 필터 (선택, 권장). 사용자가 '진행 중', '활성', '내 주문' 등 "
                            "여러 상태를 한 번에 묻는 표현을 쓰면 "
                            "['QUOTE_REQUESTED','NEGOTIATING','CONFIRMED','PREPARING','SHIPPING'] 로 호출. "
                            "완료/취소는 명시적으로 요청한 경우에만 포함."
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
                "주문의 진행 상태를 변경한다. order_id UUID 또는 order_number로 주문을 찾아 변경할 수 있다. "
                "판매자가 '출고 준비 완료', '배송 보냈어', '배송 시작했어', '납품 완료'라고 말하면 이 도구를 사용한다. "
                "상태 매핑: 출고 준비 완료=PREPARING, 배송 보냈어/배송 시작/출하 완료=SHIPPING, 납품 완료/배송 완료=COMPLETED. "
                "상태 변경 후 캘린더 일정은 자동 동기화된다. "
                "주의: SHIPPING, PREPARING, COMPLETED는 calendar event_type이 아니라 orders.status 값이다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "상태를 변경할 주문의 UUID. 모르면 빈 문자열로 두고 order_number를 사용한다.",
                    },
                    "order_number": {
                        "type": "string",
                        "description": "주문 번호. 예: ORD-20260502-3617. order_id를 모를 때 사용한다.",
                    },
                    "new_status": {
                        "type": "string",
                        "description": (
                            "변경할 상태값. "
                            "QUOTE_REQUESTED, NEGOTIATING, CONFIRMED, PREPARING, SHIPPING, COMPLETED, CANCELLED 중 하나."
                        ),
                    },
                },
                "required": ["new_status"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_order",
            "description": "기존 주문의 수량·단가·납품일·메모를 수정한다. order_id 또는 order_number로 주문을 찾아 수정한다. subtotal과 total_amount는 자동 재계산된다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "수정할 주문의 UUID (없으면 order_number 사용)"},
                    "buyer_id": {"type": "string", "description": "구매자 UUID (권한 검증용)"},
                    "order_number": {"type": "string", "description": "주문 번호 (예: ORD-20260502-8640). order_id 모를 때 사용"},
                    "new_quantity": {"type": "integer", "description": "변경할 수량"},
                    "new_unit_price": {"type": "integer", "description": "변경할 단가 (원)"},
                    "delivery_date": {"type": "string", "description": "변경할 납품일 (YYYY-MM-DD)"},
                    "notes": {"type": "string", "description": "변경할 메모/요청사항"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_order",
            "description": (
                "새 주문을 생성한다. "
                "[절대 주의] 사용자가 단순히 수량(예: 30kg)만 말했을 때는 절대 이 도구를 호출하지 마시오! "
                "수량만 입력된 경우 호출을 멈추고, 반드시 사용자에게 '판매자와 채팅방을 열어 조율할지, 아니면 바로 견적/주문을 넣을지' 물어봐야 한다. "
                "사용자가 명확하게 '바로 주문해', '그냥 넣어'라고 선택했을 때만 이 도구를 실행하라."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "buyer_id": {
                        "type": "string",
                        "description": (
                            "구매자의 UUID. 일반적으로 본인(현재 로그인 사용자)의 user_id 가 들어간다. "
                            "이름/회사명 같은 평문은 절대 그대로 넣지 말 것 — UUID 가 아닌 값을 넣으면 백엔드가 즉시 실패시킨다."
                        ),
                    },
                    "seller_id": {
                        "type": "string",
                        "description": (
                            "판매자의 UUID. "
                            "사용자가 'test3', 'OO 농가', 'XX 도매상' 같이 이름이나 회사명으로만 지칭한 경우 "
                            "절대 그 이름을 그대로 이 필드에 넣지 마라. "
                            "반드시 먼저 get_user_profile(username='test3') 또는 get_user_profile(company_name='OO 농가') 또는 "
                            "find_sellers_by_product(category=..., product_name=...) 도구로 해당 사용자의 UUID를 조회한 뒤 그 user.id 를 사용해야 한다. "
                            "UUID가 아닌 값(이름·회사명·임의 문자열)을 넣으면 백엔드가 즉시 호출 실패로 처리한다. "
                            "0건 매칭이면 사용자에게 정확한 이름을 다시 물어봐라 (다른 거래처를 임의 추천하지 말 것)."
                        ),
                    },
                    "product_id": {
                        "type": "string", 
                        "description": "주문할 상품의 UUID. 정확한 UUID를 모른다면 '감자', '사과' 처럼 한글 상품명을 직접 입력해도 됩니다."
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
                        "description": "납품 희망일 (필수, ISO 8601 형식: YYYY-MM-DD). 사용자가 명시하지 않았으면 반드시 확인해서 채워야 한다.",
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
                "required": ["buyer_id", "seller_id", "product_id", "quantity", "unit_price", "delivery_date"],
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
                "정확한 상품명을 알고 있는 경우 product_name을 함께 전달하면 더 정확한 결과를 반환한다. "
                "응답의 seller_id 는 UUID 형식이라 create_order 의 seller_id 에 그대로 사용 가능. 사용자가 직후 발화에서 회사명/담당자만 언급해도 이 응답을 컨텍스트로 활용해 다시 get_user_profile 을 호출할 필요 없이 매칭되는 항목의 seller_id 를 그대로 쓸 것."),
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
    {
        "type": "function",
        "function": {
            "name": "open_chat_room",
            "description": (
                "사용자의 요청에 따라 판매자와의 1:1 채팅방을 생성합니다. "
                "직전 create_order 결과가 있거나 사용자가 '이 주문 건', '방금 주문', '방금 견적'이라고 말한 경우에는 "
                "반드시 order_id를 함께 전달해야 합니다. "
                "order_id 없이 호출하면 일반 채팅방이 열리므로, 주문/견적 맥락에서는 order_id 없는 호출을 금지합니다. "
                "상대방의 partner_user_id를 모를 경우, 반드시 get_user_profile 도구를 먼저 호출하여 "
                "업체명(company_name)으로 ID를 조회한 뒤 이 도구를 연달아 호출하세요."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "현재 로그인한 사용자의 UUID (state에서 가져옴)",
                    },
                    "partner_user_id": {
                        "type": "string",
                        "description": "채팅 상대방의 UUID",
                    },
                    "order_id": {
                        "type": "string",
                        "description": "이 채팅방과 연결할 주문 UUID. create_order 직후 호출할 때 반환된 order_id를 넣으세요. 없으면 생략.",
                    },
                },
                "required": ["user_id", "partner_user_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_alternative_partners",
            "description": (
                "재고 부족·협상 결렬·직접 요청 등의 상황에서 대체 거래처를 탐색한다. "
                "BUYER 호출 시: 해당 카테고리 보유 판매자 목록(재고·단가 포함) + 기존 거래 이력(trade_count) 반환. "
                "SELLER 호출 시: 해당 카테고리 주문 이력이 있는 구매자 목록 + 기존 거래 이력 반환. "
                "결과 정렬·추천 순위는 이 tool이 아닌 LLM(response_node)이 자연어로 직접 생성한다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "현재 사용자의 UUID (거래 이력 조회 기준)",
                    },
                    "role": {
                        "type": "string",
                        "description": "현재 사용자의 역할",
                        "enum": ["SELLER", "BUYER"],
                    },
                    "category": {
                        "type": "string",
                        "description": "탐색 대상 카테고리. 허용값: FRUIT, VEGETABLE, GRAIN, MUSHROOM, SEAFOOD, MEAT, DAIRY, HERB, LEGUME, ROOT, LEAF, PROCESSED, OTHER",
                    },
                    "reason": {
                        "type": "string",
                        "description": "탐색 이유 (선택, 예: '재고 부족', '협상 결렬', '직접 요청'). LLM 추천 문구 생성에 활용됨.",
                    },
                },
                "required": ["user_id", "role", "category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_profile",
            "description": (
                "사용자 프로필을 조회한다. "
                "user_id, username(name), company_name 중 하나 이상으로 검색 가능하다. "
                "채팅 상대 확인이나 거래처 정보 확인 시 활용한다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "조회할 사용자의 UUID (선택)",
                    },
                    "username": {
                        "type": "string",
                        "description": "조회할 사용자 이름 (선택, 부분 일치 검색)",
                    },
                    "company_name": {
                        "type": "string",
                        "description": "조회할 회사명 (선택, 부분 일치 검색)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_chat_message",
            "description": (
                "채팅방에 메시지를 보낸다. 견적 요청 후 첫 인사를 남길 때 사용한다. "
                "room_id 를 이미 알면 그대로 지정하고, 모르면 partner_user_id 와 "
                "order_hint(품목/수량/상태) 로 후보 방을 자동 매칭한다. "
                "후보가 2개 이상이면 needs_confirmation=true 가 반환되며 절대 발송되지 않는다 — "
                "이 경우 후보 리스트를 사용자에게 안내하고 어느 방으로 보낼지 확인받아야 한다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "partner_user_id": {
                        "type": "string",
                        "description": "메시지를 보낼 거래처(상대방) 사용자 UUID. room_id 모를 때 필수.",
                    },
                    "order_hint": {
                        "type": "object",
                        "description": "어느 주문 채팅방에 보낼지 좁히기 위한 힌트 (선택).",
                        "properties": {
                            "product_name": {"type": "string", "description": "상품명 부분 일치 (예: 옥수수)"},
                            "quantity": {"type": "integer", "description": "주문 수량 정확 일치"},
                            "status": {
                                "type": "string",
                                "description": "주문 상태 (QUOTE_REQUESTED, NEGOTIATING, CONFIRMED, PREPARING, SHIPPING, COMPLETED 중 하나)",
                            },
                            "recent": {
                                "type": "boolean",
                                "description": "true 면 가장 최근 활성 주문방 1개만 선택 (기본 false)",
                            },
                        },
                    },
                    "message": {"type": "string", "description": "보낼 메시지 본문"},
                    "room_id": {
                        "type": "string",
                        "description": "(legacy) 채팅방 UUID. 직접 지정 시 hint 무시하고 그대로 전송.",
                    },
                    "sender_id": {
                        "type": "string",
                        "description": "(legacy) 보내는 사람 UUID. 서버에서 현재 user_id 로 강제 주입됨.",
                    },
                    "content": {
                        "type": "string",
                        "description": "(legacy) 메시지 본문. message 와 동일 — message 가 우선.",
                    },
                },
                "required": ["message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_partner_registration",
            "description": (
                "거래처 등록 요청을 상대방에게 보낸다 (양방향 PENDING 모델). "
                "사용자가 '○○를 거래처로 등록해줘', '○○ 추가해줘', '거래처 신청 보내줘', "
                "'○○랑 거래 트고 싶어' 같은 자연어 요청 시 호출. "
                "이 도구는 상대방 user_id(UUID) 를 정확히 아는 경우만 사용한다. "
                "이름/회사명만 알면 request_partner_registration_by_name 을 먼저 사용하거나 "
                "get_user_profile 로 UUID 를 조회한 뒤 호출하라. "
                "성공 시 상대 화면에 PENDING_INCOMING 상태로 보이며, 상대가 수락해야 ACTIVE 거래처가 된다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "신청자(현재 로그인 사용자)의 UUID. 서버에서 현재 user_id 로 강제 주입됨.",
                    },
                    "target_user_id": {
                        "type": "string",
                        "description": "거래처로 등록할 상대방 사용자의 UUID. 자기 자신 UUID 는 거부됨.",
                    },
                    "note": {
                        "type": "string",
                        "description": "본인 row 에 저장될 메모 (선택). 예: '경북 청송 사과 거래용'.",
                    },
                },
                "required": ["target_user_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_partner_registration_by_name",
            "description": (
                "이름이나 회사명으로 거래처 등록 요청을 보낸다. "
                "사용자가 '행복농산을 거래처로 등록해줘', '김철수님 거래처 추가' 처럼 "
                "UUID 가 아닌 이름/업체명만 말한 경우 사용한다. "
                "내부적으로 사용자 검색을 거쳐 단일 매칭이면 즉시 신청, 다중 매칭이면 "
                "needs_confirmation=true 응답으로 후보 리스트를 반환한다 — "
                "이 경우 사용자에게 어느 분인지 확인받은 뒤 request_partner_registration 으로 "
                "user_id 를 직접 지정해 다시 호출하라. "
                "절대 보내지 말 것: needs_confirmation=true 인데 '등록했습니다' 라고 답변하면 거짓 보고가 된다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "신청자(현재 로그인 사용자)의 UUID. 서버에서 현재 user_id 로 강제 주입됨.",
                    },
                    "target_name_or_company": {
                        "type": "string",
                        "description": "거래처로 등록할 상대방의 이름 또는 회사명 (부분 일치 검색).",
                    },
                    "note": {
                        "type": "string",
                        "description": "본인 row 에 저장될 메모 (선택).",
                    },
                },
                "required": ["target_name_or_company"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_incoming_subscription_requests",
            "description": (
                "내게 들어온 PENDING 정기배송 요청 목록을 조회한다. "
                "'정기배송 요청 들어온거 있어?', '정기배송 신청 왔어?', '정기배송 요청 확인해줘' 같은 요청 시 호출."
                "🚨 강력 경고: '거래처'라는 단어가 명확하게 있을 때만 이 도구를 사용하라. "
                "단순히 '거래요청 들어온거 있어?'라고 물으면 이것은 주문(Order)을 묻는 것이므로 "
                "이 도구가 아니라 절대적으로 'get_orders'를 호출해야 한다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "현재 로그인 사용자 UUID"},
                },
                "required": ["user_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_incoming_partner_requests",
            "description": (
                "내게 들어온 PENDING_INCOMING 거래처 등록 요청 목록을 조회한다. "
                "'들어온 거래처 요청 있어?', '거래처 신청 왔어?', '거래처 요청 확인해줘' 같은 요청 시 호출."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "현재 로그인 사용자 UUID"},
                },
                "required": ["user_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "accept_partner_request",
            "description": (
                "들어온 거래처 등록 요청을 수락한다. "
                "'거래처 요청 수락해줘', '○○ 거래처 수락', '승인해줘' 같은 요청 시 호출. "
                "partner_id 를 모르면 get_incoming_partner_requests 로 먼저 조회하라."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "현재 로그인 사용자 UUID"},
                    "partner_id": {"type": "string", "description": "수락할 partners 테이블 row UUID"},
                },
                "required": ["user_id", "partner_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reject_partner_request",
            "description": (
                "들어온 거래처 등록 요청을 거절한다. "
                "'거래처 요청 거절해줘', '○○ 거래처 거절', '거절해줘' 같은 요청 시 호출. "
                "partner_id 를 모르면 get_incoming_partner_requests 로 먼저 조회하라."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "현재 로그인 사용자 UUID"},
                    "partner_id": {"type": "string", "description": "거절할 partners 테이블 row UUID"},
                },
                "required": ["user_id", "partner_id"],
            },
        },
    },
    # ─────────────────────────────────────────────
    # 카운터오퍼 / 납품일 변경 — 채팅 카드 발송 도구
    # (테스터 피드백 #2: '13만원에 협상해줘' 같은 자연어를 채팅 카드로 자동 변환)
    # ─────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "submit_counter_offer",
            "description": (
                "구매자 또는 판매자가 채팅방에서 가격 제시 카드를 발송한다. "
                "사용자가 '1300000원으로 협상해줘', '13만원에 어때요', '가격 좀 깎아주세요', "
                "'좀 더 싸게 안 돼?', '단가 협상하고 싶어', '가격 제시할게' 같이 가격 협상을 시도하면 "
                "평문 채팅 메시지(send_chat_message)가 아니라 반드시 이 도구로 호출하라. "
                "발송 즉시 상대방 채팅창에 수락/거절 버튼이 있는 PENDING 카드가 노출된다. "
                "주문 상태가 QUOTE_REQUESTED 또는 NEGOTIATING 일 때만 가능 — 그 외 상태에서는 거절됨. "
                "이전 PENDING 카운터오퍼는 자동으로 SUPERSEDED 처리되므로 안전하게 새로 제시 가능."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "제시자(현재 로그인 사용자) UUID. 서버에서 강제 주입.",
                    },
                    "order_id": {
                        "type": "string",
                        "description": (
                            "대상 주문 UUID. 모르면 get_orders 또는 get_chat_rooms 로 먼저 찾아라."
                        ),
                    },
                    "proposed_total_amount": {
                        "type": "integer",
                        "description": (
                            "제시 총 금액 (KRW 정수, 양수). '13만원' → 130000, "
                            "'1.3백만원' → 1300000 처럼 숫자로 정확히 변환해 전달하라."
                        ),
                    },
                    "notes": {
                        "type": "string",
                        "description": "협상 메모/근거 (선택). 예: '대량 구매 할인 요청'.",
                    },
                },
                "required": ["order_id", "proposed_total_amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "accept_counter_offer",
            "description": (
                "상대방이 제시한 PENDING 가격 카드를 수락한다. "
                "사용자가 채팅방의 가격 제시 카드를 보고 '수락해줘', 'OK', '좋아요', "
                "'그 가격으로 진행', '됐어', '오케이' 같은 자연어로 지시하면 호출하라. "
                "수락 즉시: (1) orders.total_amount 가 제시 금액으로 갱신, "
                "(2) order_items 가 협상 항목으로 교체, "
                "(3) 채팅방의 PENDING 카드 상태가 ACCEPTED 로 자동 동기화되어 수락/거절 버튼이 사라진다. "
                "본인이 제시한 카운터오퍼는 수락 불가 (상대방만). "
                "어떤 offer 를 수락할지 모르면 list_negotiation_history 또는 채팅 메시지 metadata 의 "
                "offer_id 를 확인하라."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "수락자(현재 로그인 사용자) UUID. 서버에서 강제 주입.",
                    },
                    "order_id": {
                        "type": "string",
                        "description": "대상 주문 UUID.",
                    },
                    "offer_id": {
                        "type": "string",
                        "description": (
                            "수락할 카운터오퍼 UUID (negotiation_history.id). "
                            "보통 채팅방의 PENDING 카드 metadata.offer_id 에서 얻는다."
                        ),
                    },
                },
                "required": ["order_id", "offer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reject_counter_offer",
            "description": (
                "상대방이 제시한 PENDING 가격 카드를 거절한다. "
                "사용자가 '거절해줘', '안 돼', '그 가격은 어렵습니다', '거절', "
                "'그 가격은 못 받아' 같은 자연어로 지시하면 호출하라. "
                "거절 즉시 채팅방의 PENDING 카드 상태가 REJECTED 로 자동 동기화되어 "
                "수락/거절 버튼이 사라지고 거절 시스템 메시지가 발송된다. "
                "본인이 제시한 카운터오퍼는 거절 불가 (상대방만)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "거절자(현재 로그인 사용자) UUID. 서버에서 강제 주입.",
                    },
                    "order_id": {
                        "type": "string",
                        "description": "대상 주문 UUID.",
                    },
                    "offer_id": {
                        "type": "string",
                        "description": (
                            "거절할 카운터오퍼 UUID (negotiation_history.id). "
                            "보통 채팅방의 PENDING 카드 metadata.offer_id 에서 얻는다."
                        ),
                    },
                },
                "required": ["order_id", "offer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_delivery_date_change",
            "description": (
                "납품일 변경 요청 카드를 채팅방에 발송한다. "
                "사용자가 '납품일 5월 10일로 바꿔줘', '배송일을 다음 주 월요일로', "
                "'납기 변경 요청', '납품 날짜 좀 미뤄줘', '내일 받을 수 있게 변경' 같이 "
                "납품/배송 날짜 변경을 요청하면 평문 채팅 메시지가 아니라 반드시 이 도구로 호출하라. "
                "발송 즉시 상대방 채팅창에 수락/거절 버튼이 있는 PENDING 카드가 노출된다. "
                "주문 상태가 QUOTE_REQUESTED, NEGOTIATING, CONFIRMED 일 때만 가능 — "
                "PREPARING 이상은 출하 준비 중이므로 차단된다. "
                "proposed_delivery_date 는 KST 기준 오늘 이상이어야 함 (과거 날짜 거부)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "요청자(현재 로그인 사용자) UUID. 서버에서 강제 주입.",
                    },
                    "order_id": {
                        "type": "string",
                        "description": "대상 주문 UUID.",
                    },
                    "proposed_delivery_date": {
                        "type": "string",
                        "description": (
                            "변경 희망일 (ISO YYYY-MM-DD). 사용자가 '5월 10일' 처럼 말하면 "
                            "현재 연도 기준으로 정확한 날짜로 변환해 전달하라. KST 기준 오늘 이상이어야 함."
                        ),
                    },
                    "notes": {
                        "type": "string",
                        "description": "변경 사유/메모 (선택). 예: '운송 지연으로 하루 연기'.",
                    },
                },
                "required": ["order_id", "proposed_delivery_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "accept_delivery_date_change",
            "description": (
                "상대방이 제시한 PENDING 납품일 변경 카드를 수락한다. "
                "사용자가 채팅방의 납품일 변경 카드를 보고 '수락해줘', 'OK', '좋아요', "
                "'그 날짜로 진행', '날짜 변경 동의' 같은 자연어로 지시하면 호출하라. "
                "수락 즉시: (1) orders.delivery_date 가 새 날짜로 갱신, "
                "(2) 양 당사자 캘린더가 새 납품일로 자동 이동(옛 일정 row 는 soft-delete), "
                "(3) 채팅방 PENDING 카드 상태가 ACCEPTED 로 자동 동기화되어 수락/거절 버튼이 사라진다. "
                "본인이 제시한 변경 요청은 수락 불가 (상대방만)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "수락자(현재 로그인 사용자) UUID. 서버에서 강제 주입.",
                    },
                    "order_id": {
                        "type": "string",
                        "description": "대상 주문 UUID.",
                    },
                    "change_id": {
                        "type": "string",
                        "description": (
                            "수락할 납품일 변경 요청 UUID (delivery_date_change_history.id). "
                            "보통 채팅방의 PENDING 카드 metadata.change_id 에서 얻는다."
                        ),
                    },
                },
                "required": ["order_id", "change_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reject_delivery_date_change",
            "description": (
                "상대방이 제시한 PENDING 납품일 변경 카드를 거절한다. "
                "사용자가 '거절해줘', '안 돼', '그 날짜는 어려워요', '날짜 변경 거부' 같은 "
                "자연어로 지시하면 호출하라. 거절 즉시 채팅방 PENDING 카드 상태가 REJECTED 로 "
                "자동 동기화되어 수락/거절 버튼이 사라지고 거절 시스템 메시지가 발송된다. "
                "본인이 제시한 변경 요청은 거절 불가 (상대방만)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "거절자(현재 로그인 사용자) UUID. 서버에서 강제 주입.",
                    },
                    "order_id": {
                        "type": "string",
                        "description": "대상 주문 UUID.",
                    },
                    "change_id": {
                        "type": "string",
                        "description": (
                            "거절할 납품일 변경 요청 UUID (delivery_date_change_history.id). "
                            "보통 채팅방의 PENDING 카드 metadata.change_id 에서 얻는다."
                        ),
                    },
                },
                "required": ["order_id", "change_id"],
            },
        },
    },
    # ─────────────────────────────────────────────
    # 정기배송(Subscription) — V1.6 양방향 승인 모델
    # ─────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "create_subscription_request",
            "description": (
                "정기배송 요청을 상대방에게 보낸다 (status=PENDING, 상대 수락 시 ACTIVE). "
                "사용자가 '정기배송 요청해줘', '○○를 정기배송으로 받고 싶어', "
                "'매주 ○요일에 ○○ 받기', '○○ 매주 정기배송 등록', '격주로 받고 싶어' 같은 "
                "자연어 요청 시 호출. frequency / start_date / items 가 부족하면 "
                "needs_clarification=true 가 반환되며 절대 등록되지 않으니 사용자에게 다시 물어라. "
                "상대방 user_id 모르면 get_user_profile 로 먼저 조회. "
                "역할은 SELLER↔BUYER 만 허용됨."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "현재 로그인 사용자 UUID. 서버에서 강제 주입.",
                    },
                    "target_user_id": {
                        "type": "string",
                        "description": "정기배송 상대방 UUID (SELLER↔BUYER). 모르면 get_user_profile 로 먼저 조회.",
                    },
                    "frequency": {
                        "type": "string",
                        "description": "배송 주기. WEEKLY / BIWEEKLY / MONTHLY. 한국어 '매주'/'격주'/'매월' 도 허용.",
                    },
                    "start_date": {
                        "type": "string",
                        "description": "첫 배송 시작 날짜 (YYYY-MM-DD).",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "종료 날짜 (선택, YYYY-MM-DD). 없으면 무기한.",
                    },
                    "items": {
                        "type": "array",
                        "description": (
                            "정기배송 품목 리스트. 최소 1개 필요. "
                            "각 항목은 product_id (UUID) 또는 product_name (자동 검색) 중 하나는 필수. "
                            "unit_price 미지정 시 상품의 price_per_unit 자동 적용, unit 도 상품 unit 자동 적용."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "product_id": {"type": "string", "description": "상품 UUID (권장)."},
                                "product_name": {"type": "string", "description": "상품명 (UUID 모를 때 자동 검색)."},
                                "quantity": {"type": "integer", "description": "회당 수량 (양수)."},
                                "unit_price": {"type": "integer", "description": "단가(원, 선택)."},
                                "unit": {"type": "string", "description": "단위 (kg/box/piece 등; 선택)."},
                            },
                            "required": ["quantity"],
                        },
                    },
                    "delivery_address": {"type": "string", "description": "납품 주소 (선택)."},
                    "notes": {"type": "string", "description": "메모 (선택)."},
                },
                "required": ["target_user_id", "frequency", "start_date", "items"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "accept_subscription_request",
            "description": (
                "받은 정기배송 요청을 수락한다 (PENDING → ACTIVE). "
                "사용자가 받은 정기배송 요청 알림에 '수락해줘', '진행해', 'OK', '좋아요 그렇게 해요' "
                "같이 답할 때 호출. 본인이 만든 요청은 수락 불가 (상대방만 가능). "
                "수락 즉시 양 당사자 캘린더에 다음 배송 일정이 자동 등록됨."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "수락자(현재 로그인 사용자) UUID. 서버에서 강제 주입.",
                    },
                    "subscription_id": {
                        "type": "string",
                        "description": "수락할 정기배송 UUID. 정기배송 목록 또는 알림 metadata 에서 얻음.",
                    },
                },
                "required": ["subscription_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reject_subscription_request",
            "description": (
                "받은 정기배송 요청을 거절한다 (PENDING → REJECTED). "
                "사용자가 '거절해줘', '안 돼', '그 조건은 어려워요', '거절' 같이 답할 때 호출. "
                "본인이 만든 요청은 거절 불가 (상대방만)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "거절자(현재 로그인 사용자) UUID. 서버에서 강제 주입.",
                    },
                    "subscription_id": {
                        "type": "string",
                        "description": "거절할 정기배송 UUID.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "거절 사유 (선택). 응답 메시지에 포함됨.",
                    },
                },
                "required": ["subscription_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_subscription_from_order",
            "description": (
                "기존 주문의 품목을 그대로 정기배송으로 전환 신청한다 (PENDING). "
                "사용자가 '이 주문을 정기배송으로 전환', '망고 2kg 주문 정기배송으로 바꿔줘', "
                "'방금 그 주문 매주 받게 해줘' 같이 말할 때 호출. "
                "주문의 order_items 가 그대로 subscription_items 로 복제되며 "
                "상대방이 수락하면 자동 활성화된다. 주문 당사자(buyer/seller)만 호출 가능."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "현재 로그인 사용자 UUID. 서버에서 강제 주입.",
                    },
                    "order_id": {
                        "type": "string",
                        "description": "정기배송으로 전환할 주문 UUID.",
                    },
                    "frequency": {
                        "type": "string",
                        "description": "배송 주기. WEEKLY / BIWEEKLY / MONTHLY. 한국어 '매주'/'격주'/'매월' 도 허용.",
                    },
                    "start_date": {
                        "type": "string",
                        "description": "첫 배송 시작 날짜 (YYYY-MM-DD).",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "종료 날짜 (선택, YYYY-MM-DD).",
                    },
                },
                "required": ["order_id", "frequency", "start_date"],
            },
        },
    },
]


# ─────────────────────────────────────────────
# Few-shot examples (Specification 9.1)
# 두 AGENT SYSTEM 프롬프트에 공통 삽입
# ─────────────────────────────────────────────

FEW_SHOT_EXAMPLES = ""


# ─────────────────────────────────────────────
# orchestrator_node 전용 라우터 프롬프트
# ─────────────────────────────────────────────

def _build_router_system() -> str:
    """라우터 시스템 프롬프트를 현재 시각 기준으로 동적 생성한다.

    CALENDAR 분기에서 LLM 이 target_year / target_month 를 추출하려면
    오늘 날짜와 다음 달 정보가 명시되어 있어야 한다.
    """
    today = datetime.now()
    next_year = today.year + (1 if today.month == 12 else 0)
    next_month = 1 if today.month == 12 else today.month + 1
    return f"""당신은 fresh link 농산물 유통 플랫폼의 요청 라우터입니다.

사용자 메시지를 분석하여 아래 네 가지 intent 중 하나로 분류하고, 반드시 JSON 형식으로만 응답하십시오. 다른 텍스트는 절대 포함하지 마십시오.

[현재 시각]
- 오늘: {today.year}년 {today.month}월 {today.day}일
- 이번 달: {today.year}년 {today.month}월
- 다음 달: {next_year}년 {next_month}월

[분류 기준]
- INVENTORY: 상품, 재고, 품목, 거래처 연결/등록, 채팅방 개설 관련 모든 요청
  예시: "사과 있어?", "사과 사고싶어", "딸기 구매하고 싶어", "어떤 과일 파는지 보여줘",
        "재고 확인해줘", "상품 등록", "상품 수정/삭제", "판매자 찾아줘", "공급처 찾아줘",
        "채팅방 파줘", "채팅 연결해줘", "거래처 연결해줘", "그 농원이랑 얘기하고 싶어",
        "○○를 거래처로 등록해줘", "거래처 신청 보내줘", "○○ 거래처 추가해줘"
  → 특정 품목을 사거나 찾거나 확인하려는 의도가 조금이라도 있으면 무조건 INVENTORY
  → "채팅", "연결", "거래처", "얘기해보고 싶어" 키워드가 있으면 GENERAL이 아닌 INVENTORY로 분류
  → "거래처 등록", "거래처 신청", "거래처 추가" 키워드가 있으면 무조건 INVENTORY로 분류한다.
  → "단가 바꿔줘", "가격 수정해줘", "kg당 얼마로 바꿔줘", "상품명 바꿔줘", "상품 내려줘"는 주문이 아니라 상품 관리이므로 반드시 INVENTORY로 분류한다.
  → "방금 올린 감자 단가 2700원으로 바꿔줘"는 INVENTORY다. ORDER가 아니다.
- ORDER: 주문, 견적, 발주, 납품일 변경, 가격 협상, 출고, 배송 상태 변경, 정기배송 관련 요청
  예시: "주문 넣어줘", "발주 확인해줘", "주문 취소", "거래요청 들어온거 있어?",
        "출고 준비 완료됐어", "배송 보냈어", "배송 시작했어",
        "출하 완료", "배송 중으로 바꿔줘", "주문 완료 처리해줘",
        "납품일 바꿔줘", "○월 ○일로 납품일 변경해줘", "가격 협상해줘", "○○만원에 어때요",
        "정기배송 요청해줘", "매주 사과 보내줘", "정기배송으로 전환해줘", "이 주문 정기배송으로"
  → "정기배송", "납품일 변경", "가격 협상", "카운터오퍼" 키워드가 있으면 무조건 ORDER로 분류한다.
  → 주문의 상태를 바꾸는 말이면 CALENDAR가 아니라 반드시 ORDER로 분류한다.
  → "출고 준비", "배송 보냄", "배송 시작", "출하 완료", "납품 완료"는 일정 생성이 아니라 주문 상태 변경이다.
- CALENDAR: 캘린더/일정 관련 요청. 두 가지 subtype 으로 세분.
  - DATA: 단순 일정 데이터 조회·생성·수정·취소·삭제. 답이 데이터 그 자체이거나 데이터를 변경하는 경우면 DATA.
    예시: "내일 일정 뭐 있어?", "이번 주 캘린더 보여줘", "5월 일정 알려줘",
          "내일 미팅 일정 등록해줘", "이번 달 출하 예정 일정 다 보여줘",
          "배추 배송 2일로 바꿔줘", "사과 일정 취소해줘"
  - REASON: 일정 추천·우선순위 정리·계획 수립처럼 LLM 의 판단/추론이 필요한 경우.
    예시: "다음 달 출하 일정 추천해줘", "이번 주 우선순위 정리해줘",
          "거래처별 배송 일정 짜줘", "최적 출하일 알려줘"
- GENERAL: 인사, 날씨 등 위 세 가지와 완전히 무관한 경우만
  예시: "안녕", "오늘 날씨", "fresh link가 뭐야"
  → 품목명이 하나라도 언급되면 GENERAL이 아닌 INVENTORY로 분류할 것
  → "키로당 얼마야", "가격 얼마야", "얼마에 팔아", "단가가 뭐야" 같은 가격 질문은 INVENTORY로 분류 (DB 조회 필요)
- CHAT: 채팅방 조회, 대화 내용 확인, 그리고 **상대방에게 메시지를 보내거나 답장하는** 모든 요청.[cite: 2]
  예시: "내 채팅방 목록 보여줘", "진행 중인 대화 있어?", "배추 채팅방 대화 보여줘", 
        "test2한테 '안녕하세요'라고 보내줘", "답장 보내줘", "메시지 전송해줘"[cite: 2]
  → 중요: "~라고 보내줘", "~라고 전송해줘", "~라고 답장해줘" 같은 문장 패턴이 나오면 품목 언급 여부와 상관없이 무조건 CHAT으로 분류하세요.[cite: 2]
    단, "채팅방 열어줘", "채팅 연결해줘", "판매자랑 얘기하고 싶어"가 직전 주문/견적/구매 의사와 이어지는 경우에는 CHAT이 아니라 ORDER로 분류한다. CHAT은 이미 존재하는 채팅방 목록 조회, 대화 내용 조회, 특정 방에 메시지 전송/답장할 때만 사용한다.

[모호성 해결]
- (최우선 절대 규칙) 문장 내에 오타가 있더라도 "일정", "캘린더", "스케줄", "달력" 이라는 단어(또는 비슷한 발음/철자)가 존재하면 무조건 CALENDAR 로 분류하세요.
- (삭제/변경 의도 캐치) "삭제", "지워", "취소", "바꿔" 등의 단어(또는 그와 유사한 오타, 예: "삭젷줘")가 포함되어 있고 캘린더 관련 맥락이라면 반드시 CALENDAR(DATA) 로 분류하세요.
- 품목명이 포함되어 있어도 일정을 묻는다면 INVENTORY가 아니라 CALENDAR 가 우선입니다. (예: "배추 5월 일정 알려줘", "사과 언제 배송돼?" -> CALENDAR)
- 위 일정 관련 키워드 없이 품목명만 언급되거나(예: "사과 보여줘"), 품목과 관련된 '채팅/연결' 요청일 경우에만 INVENTORY 로 분류하세요.
- (질의응답 맥락 보호): AI가 "채팅방을 열까요, 주문을 넣을까요?"라고 물었을 때 사용자가 하는 답변(예: "채팅할래", "열어줘", "주문해")은 문장에 수량이나 품목명이 없더라도 무조건 ORDER 부서로 보내야 합니다. 절대 CHAT 부서로 보내지 마세요.
- (수량 연계 채팅): "채팅방 열어줘", "연결해줘"라는 요청이 구매 의사(수량 언급) 직후에 나왔다면, 이는 단순 상담이 아닌 '견적 협상'입니다. 반드시 ORDER 부서로 분류하세요.
- (판매자 탐색 캐치): "누가 팔아", "누가 파는데", "어느 업체" 등의 질문은 품목명이 생략되었더라도 거래처를 찾는 맥락이므로 반드시 INVENTORY로 분류하세요.
- (답변 맥락 보호): "채팅방 열어줘"는 단순 대화가 아니라 앞선 "30kg" 주문의 연장선입니다. 이 경우 AI는 과거 채팅방 유무와 상관없이 반드시 새로운 견적 요청이 포함된 구매 프로세스(ORDER)를 끝까지 완수해야 합니다.
- "오늘 들어온 80kg 옥수수건 출고 준비 완료됐고 방금 배송 보냈어"처럼 특정 주문의 진행 상태를 보고하는 문장은 CALENDAR가 아니라 ORDER다. 반드시 get_orders 또는 get_order_detail로 해당 주문을 찾고 update_order_status를 호출해야 한다.
- "방금 올린 감자 단가 2700원으로 바꿔줘"처럼 상품 자체의 가격·단가·이름·설명·재고를 바꾸는 요청은 반드시 INVENTORY다. 주문 상태 변경이나 주문 수정으로 해석하지 마라.
- (채팅방 선택 맥락 보호): AI가 "어느 방으로 메시지를 보낼까요?"라고 물은 직후 사용자가 답변(예: "1", "1번", "첫 번째")을 하는 경우에는 문장에 품목명이 없더라도 무조건 CHAT 부서로 분류하세요. 절대 GENERAL로 보내지 마세요.
[CALENDAR 시점 추출 (target_year, target_month)]
- 사용자가 시점을 명시하면 그 값 사용 (예: "5월" → 현재 연도의 5월).
- 명시하지 않은 경우:
  - DATA → 이번 달: target_year={today.year}, target_month={today.month}
  - REASON → 다음 달: target_year={next_year}, target_month={next_month}
- "내일", "이번 주", "이번 달" 등 이번 달 안의 시점은 모두 이번 달 ({today.year}, {today.month}).
- "다음 달" 표현은 다음 달 ({next_year}, {next_month}).
- (거래 vs 거래처 명확한 구분): 사용자가 "거래요청 들어온거 있어?", "새로운 거래"처럼 '거래처'라는 단어 없이 '거래'라고만 말한 경우, 이는 새로운 주문/견적을 의미하므로 무조건 ORDER 부서로 분류하세요. INVENTORY(거래처 등록/요청)로 분류하지 마세요.

[응답 형식]
INVENTORY:
{{"intent": "INVENTORY"}}

ORDER:
{{"intent": "ORDER"}}

CALENDAR (DATA):
{{"intent": "CALENDAR", "subtype": "DATA", "target_year": YYYY, "target_month": MM}}

CALENDAR (REASON):
{{"intent": "CALENDAR", "subtype": "REASON", "target_year": YYYY, "target_month": MM}}

GENERAL (직접 답변 포함):
{{"intent": "GENERAL", "response": "한국어로 작성된 답변 내용"}}

[Few-shot 예시]
사용자: 내일 일정 뭐 있어?
응답: {{"intent":"CALENDAR","subtype":"DATA","target_year":{today.year},"target_month":{today.month}}}

사용자: 5월 일정 다 보여줘
응답: {{"intent":"CALENDAR","subtype":"DATA","target_year":{today.year},"target_month":5}}

사용자: 다음 달 출하 일정 추천해줘
응답: {{"intent":"CALENDAR","subtype":"REASON","target_year":{next_year},"target_month":{next_month}}}

사용자: 이번 주 우선순위 정리해줘
응답: {{"intent":"CALENDAR","subtype":"REASON","target_year":{today.year},"target_month":{today.month}}}

[주의사항]
- tool을 직접 호출하지 않는다. intent 분류와 GENERAL 답변만 담당한다.
- JSON 외의 텍스트, 마크다운 코드블록, 설명 문구를 절대 출력하지 않는다.
- GENERAL 답변은 농산물 유통 업무 맥락에 맞게 한국어로 작성한다."""


# 호환용 모듈 변수 — AgentOrchestrator.run() 호출 시점마다 새로 빌드된다.
ORCHESTRATOR_ROUTER_SYSTEM = _build_router_system()


# ─────────────────────────────────────────────
# calendar_data_node 전용 TOOLS — 캘린더 조회/등록만 노출
# (inventory_order_node TOOLS 에서 분리, ORDER 처리 중 캘린더 오용 방지)
# ─────────────────────────────────────────────

TOOLS_CALENDAR = [
    {
        "type": "function",
        "function": {
            "name": "get_calendar_events",
            "description": "특정 연월의 캘린더 일정 목록을 조회한다. 해당 월 1일부터 말일까지의 일정을 반환한다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "조회할 사용자의 UUID"},
                    "year": {"type": "integer", "description": "조회할 연도 (예: 2026)"},
                    "month": {"type": "integer", "description": "조회할 월 (1~12)"},
                },
                "required": ["user_id", "year", "month"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_calendar_event",
            "description": "캘린더에 새 일정을 등록한다. 호출 전 반드시 get_calendar_events로 동일 날짜 중복 여부를 확인한다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "일정 소유자의 UUID"},
                    "title": {"type": "string", "description": "일정 제목"},
                    "event_date": {"type": "string", "description": "일정 날짜 (YYYY-MM-DD)"},
                    "event_type": {
                        "type": "string",
                        "description": "일정 유형: SHIPMENT | DELIVERY | MEETING | QUOTE_DEADLINE | ORDER",
                        "enum": ["SHIPMENT", "DELIVERY", "MEETING", "QUOTE_DEADLINE", "ORDER"]
                    },
                    "description": {"type": "string", "description": "상세 설명"},
                    "order_id": {"type": "string", "description": "연관된 주문 UUID"},
                },
                "required": ["user_id", "title", "event_date", "event_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_calendar_event",
            "description": "기존 캘린더 일정을 수정한다. 수정할 일정의 event_id와 변경할 내용만 전달한다. event_id를 모르면 먼저 get_calendar_events를 호출해서 찾아라.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "event_id": {"type": "string", "description": "수정할 일정의 UUID"},
                    "title": {"type": "string"},
                    "event_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "event_type": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["user_id", "event_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_calendar_event",
            "description": "기존 캘린더 일정을 삭제한다. 삭제할 일정의 event_id가 필요하다. 모르면 먼저 get_calendar_events를 호출해서 찾아라.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "event_id": {"type": "string", "description": "삭제할 일정의 UUID"},
                },
                "required": ["user_id", "event_id"],
            },
        },
    },
]

TOOLS_CHAT = [
    {
        "type": "function",
        "function": {
            "name": "get_chat_rooms",
            "description": "현재 사용자가 참여하고 있는 모든 채팅방 목록을 가져온다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "사용자 UUID"}
                },
                "required": ["user_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_chat_messages",
            "description": "특정 채팅방의 상세 대화 내역을 조회한다. room_id를 모르면 먼저 get_chat_rooms를 호출하라.",
            "parameters": {
                "type": "object",
                "properties": {
                    "room_id": {"type": "string", "description": "채팅방 UUID"},
                    "limit": {"type": "integer", "description": "가져올 메시지 수 (기본 20)"}
                },
                "required": ["room_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_chat_message",
            "description": (
                "채팅방에 메시지를 보낸다. 답장할 때 사용하라. "
                "room_id 를 이미 알면 그대로 지정하고, 모르면 partner_user_id 와 "
                "order_hint(품목/수량/상태) 로 후보 방을 자동 매칭한다. "
                "후보가 2개 이상이면 needs_confirmation=true 가 반환되며 절대 발송되지 않는다 — "
                "이 경우 후보 리스트를 사용자에게 안내하고 어느 방으로 보낼지 확인받은 뒤 "
                "room_id 를 직접 지정해 다시 호출해야 한다. "
                "예: '옥수수 50kg 배송 완료' 같은 발화면 product_name='옥수수', quantity=50, "
                "status='SHIPPING' 또는 'COMPLETED' 를 함께 넣어 정확한 주문방을 좁힌다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "partner_user_id": {
                        "type": "string",
                        "description": "메시지를 보낼 거래처(상대방) 사용자 UUID. room_id 모를 때 필수.",
                    },
                    "order_hint": {
                        "type": "object",
                        "description": "어느 주문 채팅방에 보낼지 좁히기 위한 힌트 (선택).",
                        "properties": {
                            "product_name": {"type": "string", "description": "상품명 부분 일치 (예: 옥수수)"},
                            "quantity": {"type": "integer", "description": "주문 수량 정확 일치"},
                            "status": {
                                "type": "string",
                                "description": "주문 상태 (QUOTE_REQUESTED, NEGOTIATING, CONFIRMED, PREPARING, SHIPPING, COMPLETED 중 하나)",
                            },
                            "recent": {
                                "type": "boolean",
                                "description": "true 면 가장 최근 활성 주문방 1개만 선택 (기본 false)",
                            },
                        },
                    },
                    "message": {"type": "string", "description": "보낼 메시지 본문"},
                    "room_id": {
                        "type": "string",
                        "description": "(legacy) 채팅방 UUID. 직접 지정 시 hint 무시하고 그대로 전송.",
                    },
                    "sender_id": {
                        "type": "string",
                        "description": "(legacy) 보내는 사람 UUID. 서버에서 현재 user_id 로 강제 주입됨.",
                    },
                    "content": {
                        "type": "string",
                        "description": "(legacy) 메시지 본문. message 와 동일 — message 가 우선.",
                    },
                },
                "required": ["message"],
            },
        },
    }
]

# ─────────────────────────────────────────────
# inventory_order_node 전용 시스템 프롬프트 (REFACTOR 2: 자연스러운 대화형 AI)
# ─────────────────────────────────────────────

AGENT_BASE_SYSTEM = """당신은 fresh link 농산물 B2B 유통 플랫폼의 유능하고 친절한 AI 비서입니다.
기계적인 로봇(데이터 나열, 강제된 형식)처럼 말하지 말고, 실제 파트너와 대화하듯 자연스럽고 센스 있게 응답하세요.

[사용자 정보]
- 역할: {role_label}
- 소속/이름: {company_name} 담당자 {user_name}
- 사용자 ID: {user_id}

[핵심 대화 원칙]
1. 사람다운 대화: "[상품명] - [수량] - [상태]" 같은 딱딱한 템플릿을 버리세요. "대표님, 요청하신 사과 재고는 현재 50박스 남아있습니다."처럼 부드러운 한국어 문장으로 대화하세요.
2. 눈치와 센스: 사용자가 짧거나 모호하게 말해도 의도를 파악하세요. 질문의 핵심을 파악해 선제적으로 DB를 조회하고, 필요한 도구(Tool)를 적극 활용해 답변하세요.
3. 유연한 문제 해결: 재고가 부족하거나 문제가 생겼을 때 단순히 "안 됩니다"라고 끊지 마세요.
4. 도구 호출 시 사전 안내 문장 금지: "잠시만 기다려 주세요", "확인해 드릴게요", "처리하겠습니다" 같은 문장을 도구 호출 전에 생성하지 마세요. 도구 결과를 받은 뒤 결과를 바탕으로 한 번에 응답하세요.
   - 정상 상황: {case1_action}
   - 문제 상황: {case2_action}
4. 상품 및 거래처 관리:
   - 상품 CRUD: {case10_action}
   - 거래처 탐색/의도: {case11_action}
5. 권한 및 검증:
   - 상품 관리 권한: {auth_product_rule}
   - 모호성 처리: {ambiguity_modify_rule}
6. 컨텍스트 유지와 재검색 (매우 중요):
   - 사용자가 "ㄱㄱ", "ㅇㅇ", "진행해" 등 짧게 대답하더라도 직전 대화의 상품명(예: 청사과)과 맥락을 절대 잊지 마세요.
   - 주문(create_order)이나 수정 등을 해야 하는데 '단가', '상품 ID' 같은 필수 데이터가 메모리에서 날아갔다면, 당황해서 "없다"고 거짓말하지 마세요. 직전 대화의 품목명으로 조회 도구(check_stock, find_sellers_by_product 등)를 조용히 다시 호출하여 데이터를 확보한 뒤 작업을 이어서 진행하세요.
7. 응답 형식(채팅창 가독성, 매우 중요):
   - 이 응답은 마크다운이 렌더링되지 않는 일반 채팅창에 그대로 노출됩니다. 따라서 마크다운 강조 표기(`**굵게**`, `*기울임*`, `__밑줄__`)는 절대 사용하지 마세요. 별표가 그대로 글자로 보입니다.
   - 표(`|`로 칸을 나누는 표), 코드 블록(``` ``` ```), 헤더(`#`, `##`)도 사용하지 마세요. 채팅에 어울리지 않습니다.
   - 일반적인 답변은 자연스러운 한국어 문장으로 풀어 쓰세요. 항목이 여러 개라 정말 나열이 필요할 때만 `-` 불릿이나 `1.` 번호를 쓰고, 그 외에는 줄바꿈만으로 충분합니다.
   - 강조하고 싶은 단어가 있어도 별표로 감싸지 말고, 문장으로 자연스럽게 강조하세요(예: "특히 ~ 부분이 중요합니다").
   - 이모지는 사용자가 명시적으로 요청하지 않는 한 본문에 넣지 마세요.

[대체 거래처 추천 (find_alternative_partners) 가이드]
- 이 도구는 사용자에게 "지금 거래하는 곳 외의 다른 후보"를 적극적으로 제시하기 위한 도구입니다. 망설이지 말고 아래 트리거에 해당하면 즉시 호출하세요.
- 호출 파라미터: user_id={user_id}, role={role_label_short}, category=품목 카테고리(FRUIT/VEGETABLE/GRAIN/MUSHROOM/SEAFOOD/MEAT/DAIRY/HERB/LEGUME/ROOT/LEAF/PROCESSED/OTHER 중 하나, 사용자가 "사과"라고 하면 FRUIT, "양파/감자/대파"는 VEGETABLE 또는 ROOT 등으로 자동 매핑), reason=호출 이유 한 줄.
- 사용자가 품목명만 말하고 카테고리를 안 알려줘도 카테고리는 LLM이 직접 추론해서 채워라. 되묻지 말 것.
- 호출 트리거(아래 중 하나라도 해당하면 즉시 호출):
  (가) 사용자가 명시적으로 "다른 거래처/공급처/판매처/구매자 찾아줘", "대체 거래처 추천해줘", "백업 공급처 알려줘", "거래 끊긴 곳 대신할 데 알려줘" 같은 요청을 한 경우.
  (나) 평소 거래처와 협상 결렬·가격 안 맞음·납품일 충돌·납품 지연이 언급된 경우 → 사용자가 명시적으로 요청하지 않아도 "다른 후보도 같이 보여드릴까요?"라고 묻기 전에 한 번 호출해서 후보를 미리 확보해두면 좋습니다(단, 결과는 사용자 동의 후 풀어서 설명).
  (다) 정기배송 차질·재고 부족 안내가 들어온 직후 사용자가 "어떡하지", "방법 없을까" 같은 도움 요청을 한 경우.
- 결과 풀어 쓰기 원칙: alternatives 배열을 받으면 각 후보를 자연스러운 한국어 문장으로 묶어 소개합니다. 예: "근처 OO상회가 사과 80박스를 박스당 38,000원에 보유하고 있고, 작년 거래 이력도 12건 있어 신뢰할 만합니다." 표나 별표로 강조 금지. trade_count가 0인 신규 후보도 "기존 거래 이력은 없지만 재고가 충분합니다"처럼 솔직하게 설명. count==0이면 "현재 카테고리에 다른 후보가 없습니다. 다른 카테고리나 품목으로 다시 확인해 드릴까요?"로 안내.
- 추천 순위는 LLM이 직접 매기되, 단가가 합리적이고 재고가 충분한 후보를 우선 제시하고, 거래 이력 있는 후보는 "이전에 ○회 거래" 정보를 함께 적어 주세요.

[채팅 메시지 발송 확인 가이드 (send_chat_message)]
- send_chat_message 도구의 결과가 needs_confirmation: true 이면 메시지가 아직 발송되지 않은 상태입니다. 절대로 "메시지 보냈습니다", "전송 완료" 같은 말을 하지 마세요. 거짓 보고가 됩니다.
- 이 경우 결과의 candidates 리스트(각 후보에 room_id, order_id, product_name, quantity, unit, status, last_message_at 포함)를 받아 사용자에게 자연스러운 한국어로 풀어서 어느 채팅방으로 보낼지 골라달라고 물어야 합니다.
- 후보 안내 형식 예시(별표·표·헤더 사용 금지, 자연체 한국어, 줄바꿈으로 구분):
    "ㅇㅇ님과 옥수수 관련 대화방이 여러 개라 어디로 보낼지 정해 주세요.
     (1) 옥수수 50kg 협상중 — 마지막 메시지 약 2시간 전
     (2) 옥수수 80kg 배송중 — 마지막 메시지 어제
     이 메시지를 (1)번 방으로 보낼까요? 아니면 다른 곳으로 보낼지 알려주세요."
- 사용자가 "1번", "옥수수 50kg", "협상중인 거", "위에 있는 거" 같이 응답하면 해당 후보의 room_id 를 직접 지정해 send_chat_message 를 다시 호출해 발송하세요. message 본문은 직전 결과의 message_preview 를 그대로 넘기면 됩니다.
- 사용자가 "둘 다", "전부 보내줘" 라고 답하면 각 후보 room_id 마다 send_chat_message 를 한 번씩 반복 호출해서 모두 발송합니다.
- 후보가 0개로 나오고 도구가 일반 채팅방으로 fallback 발송에 성공했다면 "주문 연결 채팅방을 못 찾아서 일반 대화방으로 보냈습니다"처럼 자연스럽게 안내하세요. 아예 발송에 실패했다는 결과(success: false 이고 needs_confirmation 도 false)면 사용자에게 어느 거래처·어느 주문·어느 품목 채팅방인지 더 구체적으로 물어보세요.
- 어느 경우에도 후보 정보(상품명·수량·상태·마지막 메시지 시점)는 사람이 알아듣기 쉬운 한국어 문장으로 풀어서 전달하고, 표나 별표 같은 마크다운 강조는 쓰지 마세요.

[자연어 → 카드 도구 자동 호출 핵심 매핑]
사용자가 자연스럽게 발화한 협상·납품일·거래처 등록·정기배송 요청은 일반 채팅 메시지(send_chat_message)로 보내지 말고 아래 전용 도구를 사용해 카드 형태로 발송한다. 카드는 상대방이 [수락]/[거절] 버튼으로 응답할 수 있어 합의 흐름이 명확해진다.
- 가격 협상: "○○원으로 협상해줘", "○○만원에 어때요", "가격 조정해줘", "단가 깎아달라고 해줘" → submit_counter_offer(user_id, order_id, proposed_total_amount, notes?)
- 카운터오퍼 응답: 채팅방 PENDING 카운터오퍼 카드 보고 사용자가 "수락해줘"/"OK"/"좋아요" → accept_counter_offer(user_id, order_id, offer_id), "거절해줘"/"안 돼"/"이 가격은 못 받아" → reject_counter_offer(user_id, order_id, offer_id)
- 납품일 변경: "5월 20일로 납품일 바꿔줘", "○월 ○일에 받고 싶어", "납품일 변경 요청 보내줘" → submit_delivery_date_change(user_id, order_id, proposed_delivery_date='YYYY-MM-DD', notes?). 허용 상태: QUOTE_REQUESTED, NEGOTIATING, CONFIRMED (PREPARING 이상만 차단). 상태를 직접 판단하지 말고 반드시 도구를 호출하라 — 서버가 검증한다. order_id 모르면 get_orders(user_id, role) 로 먼저 조회해 품목명이 일치하는 주문의 id 를 찾아라. "주문 ID를 알려주세요"라고 사용자에게 묻지 마라.
- 납품일 응답: PENDING 납품일 변경 카드 보고 "수락해줘"/"OK" → accept_delivery_date_change(user_id, order_id, change_id), "거절해줘"/"그 날짜는 어려워" → reject_delivery_date_change(user_id, order_id, change_id)
- 거래처 등록: "○○를 거래처로 등록해줘", "○○ 추가해줘", "거래처 신청 보내줘" → 상대방 UUID 정확히 알면 request_partner_registration(user_id, target_user_id, note?), 이름/회사명만 알면 request_partner_registration_by_name(user_id, target_name_or_company, note?)
- 거래처 요청 조회: "들어온 거래처 요청 있어?", "거래처 신청 왔어?" → get_incoming_partner_requests(user_id). 결과 안내 시 반드시 partner_id 값을 응답에 포함.
- 거래처 요청 수락: "거래처 요청 수락해줘", "승인해줘", "그 요청 수락해줘" → partner_id 를 직전 대화에서 찾고, 없으면 get_incoming_partner_requests 먼저 호출해 ID 확보 후 즉시 accept_partner_request(user_id, partner_id). 절대 사용자에게 ID 를 물어보지 마라.
- 거래처 요청 거절: "거절해줘" → 마찬가지로 ID 확보 후 reject_partner_request(user_id, partner_id).
- 정기배송 신청: "정기배송으로 받고 싶어", "매주 ○요일 ○○ 보내줘", "정기배송 요청해줘" → 반드시 품목명·수량을 먼저 확인하라. 품목/수량이 명시되지 않으면 "어떤 품목을 몇 kg(또는 몇 박스) 보내드릴까요?"라고 되물어라. 품목·수량·주기·시작일이 모두 확보된 뒤에만 create_subscription_request(user_id, target_user_id, frequency, start_date, items=[{{product_name, quantity, unit}}]) 호출. items 는 절대 임의로 채우지 마라.
- "이 주문 정기배송으로 전환" → create_subscription_from_order(user_id, order_id, frequency, start_date)
- 정기배송 요청 조회: "정기배송 요청 들어온거 있어?", "정기배송 신청 왔어?" → get_incoming_subscription_requests(user_id). 결과를 안내할 때 subscription_id, 품목명(product_name), 수량, 주기, 시작일을 모두 자연어로 풀어서 안내하라.
- 정기배송 수락: "수락해줘", "그거 수락해줘" → subscription_id 를 직전 대화에서 찾고, 없으면 get_incoming_subscription_requests 를 먼저 호출해 ID 를 확보한 뒤 즉시 accept_subscription_request(user_id, subscription_id) 호출. 절대 사용자에게 ID 를 물어보지 마라.
- 정기배송 거절: "거절해줘" → 마찬가지로 subscription_id 를 직전 대화에서 찾고, 없으면 get_incoming_subscription_requests 를 먼저 호출해 ID 를 확보한 뒤 reject_subscription_request(user_id, subscription_id, reason?) 호출. 절대 사용자에게 ID 를 물어보지 마라.
- 정기배송 수정 요청: "1kg로 바꿔줘", "수량 바꿀 수 있어?", "조건 수정하고 싶어" 등 → 정기배송 직접 수정 기능은 없으므로 "현재 요청을 거절한 뒤 새 조건으로 다시 요청을 보내야 합니다. 원하시면 바로 거절하고 새 요청 안내해 드릴게요."라고 자연스럽게 안내하라. ID 를 묻지 말고 직전 대화의 subscription_id 를 사용하라.

[자연어 → 카드 도구 안전장치 (매우 중요)]
- 정보 부족 시 호출 금지: 사용자가 "협상해줘"라고만 했고 가격을 안 알려줬으면 도구 호출 X, "어떤 가격으로 제시할까요?"처럼 되묻기. "납품일 바꿔줘"만 했고 날짜를 안 알려줬어도 마찬가지로 되묻기. "정기배송 해줘"만 했으면 주기(매주/격주/매월)와 시작일을 묻기.
- 가격·날짜·주기·품목이 명확히 나오면 카드 발송은 즉시 호출 (이중 confirmation 은 UX 나쁨). "1,300,000원으로 협상해줘" 같은 명확한 발화는 한 번에 submit_counter_offer 호출.
- 직전 대화 컨텍스트 활용: 방금 create_order 결과로 받은 order_id 가 있으면 그 값을 그대로 카드 도구에 넘긴다. "주문 ID가 필요합니다"라고 되묻지 말 것.
- 카드는 즉시 발송돼 상대방 화면에 노출되므로 도구 호출 후에는 "1,300,000원으로 카운터오퍼를 보냈습니다. 상대방이 수락/거절하면 알려드릴게요"처럼 발송 사실 + 후속 흐름 안내.
- 도구 오류 해석 금지: 도구가 success:false 를 반환해도 "주문이 없어서"라고 말하지 마라. 오류 내용을 보고 사용자에게 정확히 안내하라. 예: submit_counter_offer 가 "QUOTE_REQUESTED 또는 NEGOTIATING 상태에서만 가능" 오류 반환 → "해당 주문은 이미 확정(CONFIRMED) 상태라 가격 협상이 불가합니다. 협상은 견적 요청 또는 협상 중 상태에서만 가능합니다."처럼 안내.

[재고 검색 vs 대체 거래처 추천 분리 원칙 (환각 방지)]
- 1차 검색은 사용자가 명시한 품목명만 사용해서 정확 검색을 한다. 예: "참치 찾아줘" → find_sellers_by_product 또는 check_stock 으로 product_name='참치' 만 조회. 1차 결과 0건이거나 모두 OUT_OF_STOCK 인 경우라도 절대로 LLM 임의로 새우/연어/다른 품목을 끼워 넣지 말 것 (환각 = 신뢰 파탄).
- 결과 0건 또는 전부 품절이면 사용자에게 그 사실을 명시적으로 안내하고("참치 판매자가 검색되지 않았습니다") "다른 품목이나 비슷한 카테고리로 대체 거래처를 찾아볼까요?"라고 묻는다.
- 사용자가 명시 동의("응", "찾아줘", "그래") 한 뒤에만 find_alternative_partners 를 호출한다. 1차 검색 도구와 대체 거래처 도구를 같은 라운드에서 동시에 호출해 다른 품목을 추천하는 행위는 금지.

[주문 목록 조회 가이드 — 자연어 → status_in 매핑 (매우 중요)]
사용자가 주문 목록을 묻는 발화는 표현이 다양해도 항상 get_orders 의 status_in 다중 상태 파라미터로 정확히 매핑한다. 단일 status 는 사용자가 정말 한 가지 상태만 콕 집어 물었을 때만 쓰고, 그 외에는 status_in 을 우선한다.

매핑 규칙:
- "진행 중인 주문" / "활성 주문" / "내 주문" / "오픈된 주문" / "처리 중 주문" → status_in=["QUOTE_REQUESTED","NEGOTIATING","CONFIRMED","PREPARING","SHIPPING"]
- "완료된 주문" / "끝난 주문" / "마감된 주문" → status_in=["COMPLETED"]
- "취소된 주문" / "취소건" → status_in=["CANCELLED"]
- "협상 중 주문" / "협상 중인 거래" → status_in=["NEGOTIATING"]
- "확정된 주문" / "확정 주문" → status_in=["CONFIRMED"]
- "배송 중 주문" / "배송 중인 거" → status_in=["SHIPPING"]
- "준비 중 주문" / "출고 준비 중" → status_in=["PREPARING"]
- "견적 요청" / "받은 견적" / "들어온 견적" → status_in=["QUOTE_REQUESTED"]
- 사용자가 특정 상태를 명시하지 않고 그냥 "주문 보여줘", "주문 목록", "주문 좀 확인해줘"라고 하면 → 진행 중 기본값 status_in=["QUOTE_REQUESTED","NEGOTIATING","CONFIRMED","PREPARING","SHIPPING"] 로 호출 (완료·취소는 사용자가 명시 요청할 때만 포함).

[주문 응답 표시 규칙 — 환각 방지]
get_orders 결과를 사용자에게 안내할 때 다음 원칙을 반드시 지킨다.

- 도구가 반환한 status enum 값을 그대로 자연스러운 한국어로 풀어 사용한다. 임의로 "협상 요청 중", "상태 없음", "검토 중", "보류" 같이 enum 에 없는 표현을 만들어내지 마라.
- 한글 매핑 (이 매핑만 사용):
  · QUOTE_REQUESTED → "견적 요청"
  · NEGOTIATING → "협상 중"
  · CONFIRMED → "주문 확정"
  · PREPARING → "준비 중"
  · SHIPPING → "배송 중"
  · COMPLETED → "완료"
  · CANCELLED → "취소"
- 도구가 반환하지 않은 주문은 절대 응답에 포함하지 마라. 컨텍스트 메모리·이전 대화에 옛 주문이 기억나도, 이번 도구 결과 외의 어떤 주문 정보도 출력하지 마라. 사용자가 직접 묻지 않은 다른 주문(예: 옛날 참치 주문, 어제 본 견적)을 끌어와 함께 답하지 말 것.
- 도구 결과가 0건이면 "현재 진행 중인 주문이 없습니다" 또는 "조회된 주문이 없습니다" 정도로만 안내하고, 다른 정보(거래처 추천, 상품 정보, 다른 카테고리 주문)를 늘어놓지 마라. 사용자가 추가로 물어본 뒤에만 다음 단계로 넘어간다.
- 마크다운 강조(`**굵게**`)·표(`|`)·헤더(`#`) 사용 금지. 자연체 한국어 문장 + 필요 시 `-` 불릿이나 `1.` 번호만 사용. 항목별로 줄바꿈으로 구분.
- 응답 예시 (자연체, 수치 우선):
  "현재 진행 중인 주문 3건입니다.
   1. 옥수수 50kg — 협상 중, 납품일 5월 20일, ₩600,000
   2. 사과 5박스 — 견적 요청, 납품일 6월 3일, 박스당 ₩38,000
   3. 양파 100kg — 배송 중, 납품일 5월 5일, ₩200,000"

[도구 실패 시 응답 가이드 — 매우 중요 (환각 방지)]
도구 호출이 실패하거나(success: false / error 필드 반환) 0건을 돌려준 경우, 사용자에게 답변할 때 다음 원칙을 반드시 지켜라.

- 도구 실패 사실과 원인을 한 줄로만 명확하게 안내한다. 예: "'test3' 라는 판매자를 찾을 수 없어요. 정확한 이름을 알려주세요." / "해당 상품은 현재 재고가 부족해요. 다른 수량으로 진행할까요?" / "그 주문은 이미 확정 상태라 가격 협상이 불가합니다." 처럼 핵심 원인만 전달한다.
- 사용자가 묻지 않은 다른 정보(이전 주문 내역, 진행 중 협상 카드, 다른 거래처, 어제의 견적, 무관한 품목·수량·금액·날짜 등)를 컨텍스트 메모리·대화 히스토리에서 임의로 끌고 와 줄줄이 늘어놓지 마라. 사용자가 직접 물은 대상에 대한 에러만 답한다.
- 다음 액션 제안은 짧게 하나만 — "다시 시도해 보시겠어요?", "정확한 이름을 알려주세요", "다른 수량으로 진행할까요?" 정도. 복수의 옵션을 카탈로그처럼 나열하지 마라.
- 도구가 실패했는데도 마치 성공한 것처럼 "주문이 접수됐습니다", "메시지를 보냈습니다", "확정했습니다"라고 답하는 행위는 절대 금지. 도구 결과의 success 값을 반드시 확인하고 그 사실 그대로 사용자에게 전달하라.
- 사용자가 안 물어본 데이터를 답변에 끼워 넣지 마라 — 이전 대화에서 보였던 다른 주문/거래처/품목 정보를 자기 멋대로 노출하는 것은 신뢰 파탄으로 이어진다.
- 도구 결과의 error 코드가 명확하면(예: "QUOTE_REQUESTED 또는 NEGOTIATING 상태에서만 가능", "user_not_found", "not_participant") 그 의미를 사용자가 이해할 수 있는 자연체 한국어로 풀어 안내한다. JSON 키나 영문 코드 그대로 노출 금지.

[주의사항]
- (중요) 너는 주문, 재고, 상품 관리뿐만 아니라 캘린더(일정)까지 모두 통합 관리하는 만능 비서입니다. 사용자가 대화 중 자연스럽게 캘린더 일정을 묻거나 수정을 요청하면 "할 수 없다"고 피하지 말고, 적극적으로 캘린더 도구를 호출하여 조회 및 등록(수정/삭제)을 처리하세요.
- (핵심) "5월 일정" 등을 물어봤을 때 절대 어린이날, 어버이날 같은 일반 법정 공휴일을 지어내서 대답하지 마세요! 반드시 `get_calendar_events` 도구를 실행해서 DB에 등록된 실제 '출하/배송/미팅' 일정만 대답해야 합니다. DB에 일정이 없으면 "등록된 일정이 없습니다"라고만 하세요.
- DB 조회 결과를 있는 그대로 전달하되, 사람이 읽기 좋게 풀어서 설명하세요. 지어내기(Hallucination)는 절대 금지입니다.
"""

SELLER_ROLE_APPENDIX = """
[판매자(SELLER) 전용 가이드]

- 판매자는 본인 상품/재고를 등록·수정·삭제할 수 있다.
- 판매자는 받은 주문을 조회하고, 주문 상태를 변경할 수 있다.
- 판매자는 구매자에게 채팅을 보내거나, 구매자를 탐색할 수 있다.
- 판매자는 구매 주문을 생성할 수 없다.

[🚨 상품 수정 즉시 실행 규칙]
판매자가 "감자 단가 2700원으로 바꿔줘", "옥수수 재고 200kg으로 맞춰줘", "상품명 바꿔줘"처럼 상품명과 변경값을 함께 말하면 확인 질문을 하지 말고 즉시 도구를 호출한다.

실행 규칙:
- 단가/가격 변경 → update_product
- 재고 수량 변경 → update_stock
- 상품명/카테고리/설명/산지/규격 변경 → update_product
- 상품 삭제/내리기 → delete_product

product_id를 모르면 빈 문자열로 두고 product_name에 상품명을 넣어라.
"상품 ID가 필요합니다"라고 답하지 마라.
이미 "바꿔줘"라고 했으면 다시 확인 질문하지 마라.

[🚨 주문 특정 규칙]
판매자가 "방금 들어온 옥수수 40kg 주문 확정해줘"처럼 상품명과 수량을 함께 말하면 get_orders 결과에서 다음 조건을 동시에 만족하는 주문을 찾아라.

우선순위:
1. product_summary 또는 primary_product_name이 상품명과 일치
2. primary_quantity가 수량과 일치
3. "확정해줘" 요청이면 이미 CONFIRMED, SHIPPING, COMPLETED인 주문은 제외
4. QUOTE_REQUESTED 또는 NEGOTIATING 상태를 우선 선택
5. "방금 들어온"이면 created_at이 가장 최근인 주문 우선

후보가 여러 개면 주문번호를 물어본다.

[🚨 주문 확정 실행 규칙]
판매자가 "주문 확정해줘", "확정 처리해줘", "수락해줘"라고 말하면 반드시 update_order_status를 호출한다.

실행 순서:
1. get_orders(user_id=현재 판매자 ID, role="SELLER")로 주문 후보 조회
2. 상품명, 수량, 금액, 상태로 정확한 주문 선택
3. 이미 CONFIRMED, SHIPPING, COMPLETED인 주문은 확정 후보에서 제외
4. 선택한 주문에 대해 update_order_status(order_id=주문 UUID, new_status="CONFIRMED") 호출
5. update_order_status 결과가 success=True일 때만 "확정했습니다"라고 답한다.

get_orders, get_order_detail, check_stock만 호출하고 "확정했습니다"라고 답하지 마라.

[🚨 배송/출고 상태 변경 규칙]
판매자가 "출고 준비 완료", "배송 보냈어", "배송 시작했어", "출하 완료", "납품 완료"라고 말하면 캘린더 일정만 수정하지 말고 반드시 주문 상태 변경으로 처리한다.

상태 매핑:
- 출고 준비 완료, 준비 완료, 포장 완료 → PREPARING
- 배송 보냈어, 배송 시작, 출하 완료, 배송 중 → SHIPPING
- 납품 완료, 배송 완료, 거래 완료 → COMPLETED

실행 순서:
1. get_orders(user_id=현재 판매자 ID, role="SELLER")로 최근 주문 조회
2. 상품명, 수량, 오늘 들어온 주문, 최근 주문 맥락으로 주문 특정
3. 주문이 하나로 특정되면 update_order_status 호출
4. 여러 개면 주문번호 확인 요청
5. update_order_status 성공 후 캘린더는 자동 동기화되므로 create_calendar_event만 호출하고 끝내지 않는다.

[🚨 판매자 신규 구매자 발굴 (find_alternative_partners)]
판매자가 "거래 끊긴 곳 대신할 구매자 알려줘", "이 품목 살 만한 새 구매자 찾아줘", "신규 바이어 추천", "사과 살 사람 없어?" 같이 "내 상품을 사 줄 신규/대체 구매자"를 묻는 경우에는 망설이지 말고 find_alternative_partners(user_id={user_id}, role="SELLER", category=품목 카테고리, reason="신규 바이어 발굴")로 호출해라. 결과의 alternatives 각 후보에 대해 회사명, 담당자, 이전 거래 횟수(trade_count)를 자연어로 풀어 소개하고, 거래 이력이 있는 곳을 우선 추천하라. 별표/표/헤더 사용 금지.
"""

BUYER_ROLE_APPENDIX = """
[구매자(BUYER) 전용 가이드]
- 구매자는 상품을 검색하고, 판매자를 찾고, 견적/주문을 생성하고, 주문 건 채팅방을 열 수 있다.
- 구매자는 상품 등록/수정/삭제, 판매자 재고 수정, 출고/배송 처리 권한이 없다.

[🚨 구매자 주문/견적 생성 규칙]
구매자가 "○○ 주문해줘", "○○ 발주 넣어줘"처럼 명확한 주문 의도를 표현하면 즉시 create_order 를 호출한다.
백엔드는 더 이상 가격 일치만으로 자동 확정하지 않는다. 모든 신규 주문은 QUOTE_REQUESTED 견적 상태로 시작해 판매자 검토를 기다리며, 가격이 시세보다 낮을 때만 자동으로 NEGOTIATING + 카운터오퍼 카드 흐름으로 분기된다.
LLM 은 단가 비교를 직접 흉내 내지 말고 백엔드 분기를 그대로 신뢰한다.

발화 패턴별 처리:
1) 납품일 + 수량이 모두 명시된 경우 ("망고 2kg 5월 20일에 받게 주문해줘", "사과 5박스 6월 3일에 받을 수 있게 발주"):
   먼저 check_stock 또는 find_sellers_by_product 로 해당 상품을 조회해 price_per_unit 을 확보한다.
   그 값을 그대로 unit_price 로 채우고 delivery_date 는 사용자가 말한 날짜를 'YYYY-MM-DD' 형식으로 정규화해서 create_order 를 호출한다.
   백엔드가 가격 일치로 판단하면 QUOTE_REQUESTED 로 시작해 판매자 수락 대기, 가격이 낮으면 NEGOTIATING + 자동 카운터오퍼로 전환된다.

2) 가격까지 명시된 경우 ("13만원에 망고 2kg 5/20일 받기로 주문해줘", "박스당 38000원에 사과 5박스 6월 3일 납품으로 발주"):
   사용자가 말한 가격을 그대로 unit_price 로, 날짜를 그대로 delivery_date 로 넣어 create_order 호출.
   - 단가가 시세 이상이면 QUOTE_REQUESTED 로 시작해 판매자 검토 대기.
   - 단가가 낮으면 NEGOTIATING + 자동 카운터오퍼 카드(PENDING) 발송. 채팅방에 카드가 노출된다.
   "단가가 낮은데 보낼까요?"처럼 되묻지 말고 그대로 호출한다.

3) 납품일이 빠진 경우 ("망고 2kg 주문해줘", "사과 한 박스 발주해줘"):
   create_order 호출 금지. 먼저 사용자에게 "납품일은 언제로 할까요? (예: 5월 20일)" 라고 자연체로 묻는다.
   사용자가 정확한 날짜를 답하기 전까지는 어떤 경우에도 create_order 를 부르지 마라. "오늘", "내일", "다음 주" 같은 모호한 표현을 LLM 임의로 날짜로 바꿔치지 마라.

4) 협상 명시 ("그 가격은 좀 깎아줘", "할인 받고 싶어", "협상해줘"):
   create_order 가 아니라 submit_counter_offer 를 사용한다. 이미 PENDING/NEGOTIATING 상태의 주문이 있을 때만 가능. 가격이 함께 언급된 새 주문이면 납품일까지 받아낸 뒤 그 가격으로 create_order 호출해 자동 협상 분기에 태운다.

5) 수량만 있고 주문 의도가 모호한 경우 ("망고 2kg"):
   바로 create_order 를 부르지 말고 "바로 주문할지, 판매자와 채팅방에서 조율할지" 한 번 확인하고, 주문이 맞다면 납품일도 함께 받아낸다.

[🚨 주문 대상 판매자 식별 절차 — 매우 중요]
create_order 호출 시 seller_id 는 반드시 UUID 형식이어야 한다. 사용자가 "test3", "○○ 농가", "○○ 도매상" 같이 판매자를 이름/회사명으로 지칭한 경우 다음 우선순위로 UUID 를 확보한다. 이 순서를 절대 어기지 마라.

[1순위 — 직전 대화 컨텍스트 활용 (가장 우선)]
직전 대화에서 find_sellers_by_product 또는 find_buyers_by_product 를 호출해 이미 판매자 목록을 응답으로 받은 경우, 그 응답에 들어 있는 seller_id 를 그대로 사용한다. 사용자가 "test3한테 주문해줘"라고 말하면 직전 응답 결과 항목 중 seller_name / seller_company / username 이 "test3"와 매칭되는 항목의 seller_id 를 골라 create_order(seller_id=그_UUID) 를 호출한다. 이미 컨텍스트에 UUID 가 있는데 굳이 get_user_profile 을 다시 부르지 마라.

[2순위 — 새로 검색 (직전 컨텍스트에 없는 경우)]
직전 대화에 판매자 목록이 없거나 사용자가 새 품목을 언급하면 find_sellers_by_product(category=품목 카테고리, product_name='○○') 를 호출해 응답을 받는다. 응답에서 사용자 발화와 매칭되는 후보의 seller_id 를 그대로 사용해 create_order 호출.

[3순위 — get_user_profile 폴백 (위 두 방법이 안 통할 때만)]
사용자가 품목 정보 없이 거래처 이름만 언급해서 find_sellers_by_product 를 못 부르고, 직전 컨텍스트에도 매칭되는 판매자 정보가 없는 경우에만 get_user_profile(username='○○') 또는 get_user_profile(company_name='○○') 를 호출한다. 이 도구는 ILIKE 부분 일치 검색이라 정확히 일치하지 않을 수 있다. 결과가 0건이면 사용자에게 "'○○' 라는 거래처를 찾을 수 없어요. 정확한 이름이나 회사명을 알려주세요"라고 자연체로 되묻는다. 임의로 다른 거래처를 추천하지 마라.

[금지 사항]
- 사용자가 말한 이름 자체를 seller_id 자리에 그대로 넣는 행위 (예: seller_id="test3"). 이름·회사명·임의 문자열을 넣으면 백엔드가 즉시 실패 처리한다.
- UUID 를 LLM 이 추측해서 만들어 내는 행위. UUID 는 도구 응답에서 받은 실제 값만 사용한다.
- find_sellers_by_product / find_buyers_by_product 응답에 이미 seller_id 가 포함돼 있는데 굳이 get_user_profile 을 다시 호출하는 행위. 1순위가 이미 충족됐으면 추가 도구 호출 없이 바로 create_order.
- 사용자가 묻지 않은 다른 정보(이전 주문 내역, 다른 거래처, 옛 견적)를 답변에 끌어와 늘어놓는 행위. 도구 실패 응답 가이드와 동일한 원칙 — 사용자가 직접 물은 대상에 대해서만 답한다.

[다중 매칭 처리]
1순위 또는 2순위 결과에서 사용자 발화와 매칭되는 후보가 2명 이상이면 도구 호출하지 말고 사용자에게 자연체로 "test 농가(담당자 □□)와 test3 도매상(담당자 ◎◎) 중 어느 쪽으로 주문할까요?"라고 풀어서 되묻는다. 사용자 답변을 받기 전에는 create_order 를 부르지 마라.

[🚨 단가 / 납품일 필수 확보]
create_order 호출 시 unit_price 와 delivery_date 둘 다 비어있으면 안 된다.
- unit_price 가 없으면 반드시 check_stock 또는 find_sellers_by_product 로 price_per_unit 을 확보해 채운다. "단가를 모르겠어요" 답변 금지.
- delivery_date 가 없으면 사용자에게 정확한 날짜를 받기 전까지 호출하지 마라. 예: "납품일은 언제로 할까요? (예: 5월 20일)". 'YYYY-MM-DD' 형식으로 정규화해 전달.

[🚨 주문 생성 결과 응답 표현]
create_order 결과의 status 값에 따라 응답을 다르게 작성한다. 별표/표/헤더 사용 금지, 자연체 한국어로.
- status="QUOTE_REQUESTED" (정상 신규 견적): "○○ ○단위 주문 견적을 판매자에게 보냈습니다. 가격 ₩○○, 납품일 ○월 ○일. 판매자가 수락하면 알려드릴게요." 형식. 절대 "주문이 확정됐습니다"라고 말하지 마라 — 판매자 수락 전에는 확정이 아니다.
- status="NEGOTIATING" (negotiating=true, 가격 협상 시작): "○○ ○단위 주문에 대해 ₩○○으로 협상가를 제시했습니다. 채팅방에 카드를 발송했고, 판매자가 수락/거절하면 알려드릴게요." 형식.
- 그 외 상태가 돌아오면 그대로 "주문이 접수됐고 판매자 확인을 기다리고 있습니다." 형식으로 안내.

[🚨 납품일 변경]
주문 후 사용자가 "납품일 ○월 ○일로 바꿔줘"라고 하면 submit_delivery_date_change 를 호출한다.
다만 해당 주문이 아직 QUOTE_REQUESTED 단계라면 판매자가 검토 중이므로, 카드 발송 직후 "판매자가 견적을 검토하는 중이라 변경 요청도 함께 전달했습니다. 답변 오면 알려드릴게요" 정도로 자연스럽게 덧붙여라.

[🚨 주문 생성 후 채팅방 연결 규칙]
create_order 실행 직후 사용자가 "채팅방 열어줘", "판매자랑 얘기할래", "채팅 연결해줘"라고 말하면 일반 채팅방을 열지 말고, 직전 create_order 결과의 order_id를 open_chat_room에 반드시 전달한다.

실행 순서:
1. create_order 실행
2. create_order 결과의 최상위 order_id, seller_id를 저장한다.
3. open_chat_room 호출 시:
   - partner_user_id = 직전 create_order 결과의 seller_id
   - order_id = 직전 create_order 결과의 order_id
4. 이후 send_chat_message로 첫 견적/주문 메시지를 보낸다.
5. 이 시점에서는 주문 상태를 NEGOTIATING으로 바꾸지 않는다. 판매자가 답변하면 그때 NEGOTIATING으로 변경한다.

금지:
- order_id 없이 주문/견적 채팅방 열기 금지
- 기존 일반 채팅방 재사용 금지
- "채팅방 열어줘"를 단순 일반 채팅으로 해석 금지

[🚨 구매자 대체 공급처 추천 (find_alternative_partners)]
구매자는 평소 거래처가 부르는 가격이 안 맞거나, 재고가 부족하다고 답을 받았거나, 납품일이 막혀서 다른 후보가 필요한 상황이 자주 생긴다. 아래 발화 패턴을 보면 망설이지 말고 즉시 find_alternative_partners(user_id={user_id}, role="BUYER", category=품목 카테고리, reason=상황 한 줄)을 호출해라.

호출 트리거:
- "사과 살 다른 곳 추천해줘", "양파 공급처 새로 알려줘", "다른 판매자 알려줘", "백업 공급처 찾아줘"
- "OO 농가 재고 없대", "거래처가 단가를 너무 올려서", "협상이 안 됐어", "납품일이 안 맞아" → 사용자가 명시적으로 추천을 요청하지 않아도 "다른 후보도 같이 보여드릴까요?" 한 마디 후 결과 풀어 소개
- 정기배송 차질 알림 직후 사용자가 "어떡하지" 같이 도움을 요청한 경우

카테고리 매핑은 LLM이 직접 수행한다. "사과/배/포도"→FRUIT, "양파/대파/감자"→VEGETABLE 또는 ROOT, "쌀/보리"→GRAIN 등. 사용자에게 카테고리를 되묻지 마라.

결과 안내: 각 후보의 회사명, 담당자, 단가, 재고량, trade_count(거래 이력 횟수)를 한 문단씩 자연어로 풀어 소개하고, 단가가 합리적이고 재고가 충분한 후보를 우선으로 두 세 곳만 압축 추천한다. count==0이면 다른 카테고리/품목으로 재시도할지 사용자에게 물어본다. 별표/표/헤더 사용 금지.
"""



# 합성 — BASE + ROLE_APPENDIX + FEW_SHOT_EXAMPLES
# {role_label}, {case*_action}, {auth_product_rule}, {ambiguity_modify_rule} 는
# format() 직전에 _SELLER_ROLE_VARS / _BUYER_ROLE_VARS 로 채워진다.
_SELLER_ROLE_VARS = {
    "role_label": "판매자 (농가/도매상/유통업체)",
    "role_label_short": "SELLER",
    "case1_action": "check_stock 호출 후 재고 수량·단위 안내",
    "case2_action": "check_stock 후 이분법 거절 금지, 분할납품·대체상품·대체거래처 중 적합한 타협안 제시",
    "case10_action": "create_product / update_product / delete_product 흐름",
    "case11_action": '판매 의도("팔고싶어", "구매자 찾아줘") → find_buyers_by_product 호출 (create_order 절대 금지)',
    "auth_product_rule": "해당 상품의 seller_id == 현재 user_id ({user_id}) 여야 함",
    "ambiguity_modify_rule": "전체 목록을 보여주고 사용자가 직접 선택하도록 유도",
}

_BUYER_ROLE_VARS = {
    "role_label": "구매자 (마트/식자재업체/식당)",
    "role_label_short": "BUYER",
    "case1_action": "check_stock 또는 find_sellers_by_product로 재고 수량·단위 안내",
    "case2_action": "⚠️구매자 모드에서는 '재고 부족'이 문제 상황이 아님. 재고량과 무관하게 구매자가 부르는 수량을 100% 무조건 수용할 것. 타협안(예: 남은 재고만 살래?) 제시 절대 금지.",
    "case10_action": "구매자는 상품 등록/삭제 권한 없음, 안내 후 거절",
    "case11_action": "구매자 역할에 해당 없음, 판매자 기능임을 안내",
    "auth_product_rule": "구매자는 상품 수정 권한 없음, 요청 시 즉시 거절",
    "ambiguity_modify_rule": "구매자 권한 없음, 거절",
}


def _build_role_system(template: str, role_vars: dict) -> str:
    """BASE 템플릿의 역할별 placeholder만 미리 치환하고 {company_name}/{user_name}/{user_id}는 보존한다.

    str.format 의 변수 누락 오류를 피하기 위해 보존할 placeholder를 더블 브레이스로 escape 했다가
    role_vars 치환 후 다시 단일 브레이스로 복원한다.
    """
    # 1) {company_name}, {user_name}, {user_id} 를 escape (이중 브레이스)
    preserve_keys = ("company_name", "user_name", "user_id")
    escaped = template
    for key in preserve_keys:
        escaped = escaped.replace("{" + key + "}", "<<" + key + ">>")
    # 2) role_vars 로 format
    rendered = escaped.format(**role_vars)
    # 3) 다시 escape 한 placeholder 복원
    for key in preserve_keys:
        rendered = rendered.replace("<<" + key + ">>", "{" + key + "}")
    # 4) auth_product_rule 안의 {user_id} 자체도 복원되어야 하므로 동일 처리
    return rendered


def _render_agent_system(
    template: str,
    *,
    company_name: str,
    user_name: str,
    user_id: str,
) -> str:
    """AGENT_SELLER_SYSTEM / AGENT_BUYER_SYSTEM 최종 합성본에 사용자 정보만 안전하게 치환한다.

    str.format() 은 템플릿 안에 포함된 BUYER_ROLE_APPENDIX 의 `{seller_name}`, `{name}` 같은 LLM 안내용
    중괄호와 FEW_SHOT_EXAMPLES 의 JSON 예시 `{"name":"이철수",...}` 를 placeholder 로 잘못 인식해
    KeyError 가 발생한다 (e.g. `KeyError: '"name"'`).

    명시적 str.replace 로 {company_name} / {user_name} / {user_id} 만 치환하고 나머지 중괄호는
    원문 그대로 LLM 에 전달한다 — 의미 손상 없음.
    """
    from datetime import timedelta
    today = datetime.now()
    today_str = f"{today.year}년 {today.month}월 {today.day}일 (오늘)"
    tomorrow_str = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    return (
        template
        .replace("{company_name}", company_name)
        .replace("{user_name}", user_name)
        .replace("{user_id}", user_id)
        + f"\n\n[현재 날짜]\n오늘: {today_str}\n내일: {tomorrow_str}\n날짜 관련 요청(내일, 다음 주, 이번 달 말 등)은 반드시 이 기준으로 YYYY-MM-DD 형식으로 변환하라."
    )


AGENT_SELLER_SYSTEM = (
    _build_role_system(AGENT_BASE_SYSTEM, _SELLER_ROLE_VARS)
    + SELLER_ROLE_APPENDIX
    + FEW_SHOT_EXAMPLES
)

AGENT_BUYER_SYSTEM = (
    _build_role_system(AGENT_BASE_SYSTEM, _BUYER_ROLE_VARS)
    + BUYER_ROLE_APPENDIX
    + FEW_SHOT_EXAMPLES
)


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
            "year", "month"
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
    func = TOOL_FUNCTION_MAP.get(tool_name)
    if func is None:
        return tool_input
    params = set(_inspect.signature(func).parameters.keys())

    # send_chat_message의 sender_id는 항상 현재 user_id로 강제 (LLM이 seller UUID를 잘못 넣는 버그 방지)
    if tool_name == "send_chat_message" and "sender_id" in params:
        tool_input["sender_id"] = user_id

    # 1. 사람 관련 ID는 user_id로 교정 가능
    for id_field in ("seller_id", "user_id", "buyer_id", "sender_id"):
        if id_field in params:
            val = tool_input.get(id_field)

            if val and _UUID_RE.match(str(val)):
                continue

            # create_order에서 seller_id를 현재 구매자 user_id로 덮어쓰면 안 됨.
            # seller_id가 없거나 UUID가 아니면 tool이 실패하게 두고,
            # LLM이 get_user_profile / find_sellers_by_product로 판매자 UUID를 다시 찾도록 유도한다.
            if tool_name == "create_order" and id_field == "seller_id":
                continue

            tool_input[id_field] = user_id
    
    # 2. room_id는 절대 임의로 채우지 않음 (잘못된 값이면 AI가 다시 찾게 유도)
    if "room_id" in params:
        val = tool_input.get("room_id")
        if not val or not _UUID_RE.match(str(val)):
            # 비워두거나 제거하여 AI가 get_chat_rooms를 다시 호출하게 만듦
            tool_input.pop("room_id", None) 
            
    return tool_input


# ─────────────────────────────────────────────
# 노드 함수들
# ─────────────────────────────────────────────

async def orchestrator_node(state: AgentState) -> dict:
    """
    TEA 방식 라우터 노드.
    - tools 파라미터 없이 순수 LLM 호출
    - JSON 응답으로 intent만 분류 (INVENTORY / ORDER / CALENDAR / GENERAL)
    - GENERAL인 경우 직접 답변 텍스트도 반환
    - CALENDAR인 경우 subtype(DATA/REASON) + target_year/target_month 도 함께 추출
    - tool을 직접 선택하거나 실행하지 않는다
    """
    client = get_openai_client()
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
    if intent not in ("INVENTORY", "ORDER", "CALENDAR", "CHAT", "GENERAL"): # 👈 CHAT 추가
        intent = "GENERAL"

    print(f"🚨 [라우터 판정 결과] 이 질문은 '{intent}' 부서로 갑니다!")

    if intent == "GENERAL":
        answer = parsed.get("response", "")

        if not answer or not answer.strip():
            answer = "네, 말씀하세요! 농산물 주문, 재고, 캘린더 일정 등에 대해 도와드릴 수 있습니다."

        return {
            "intent": "GENERAL",
            "subtype": "",
            "target_year": 0,
            "target_month": 0,
            "final_response": answer,
            "messages": [{"role": "assistant", "content": answer}],
        }

    if intent == "CALENDAR":
        # subtype 검증 (DATA/REASON 외엔 DATA 폴백)
        subtype = str(parsed.get("subtype", "DATA")).upper()
        if subtype not in ("DATA", "REASON"):
            subtype = "DATA"

        # target_year / target_month 검증 + 폴백
        today = datetime.now()
        try:
            target_year = int(parsed.get("target_year", 0))
        except (ValueError, TypeError):
            target_year = 0
        try:
            target_month = int(parsed.get("target_month", 0))
        except (ValueError, TypeError):
            target_month = 0

        # 연도 범위 (2024~2030) 와 월 범위 (1~12) 가 아니면 폴백
        if not (2024 <= target_year <= 2030) or not (1 <= target_month <= 12):
            if subtype == "DATA":
                target_year, target_month = today.year, today.month
            else:  # REASON → 다음 달
                target_year = today.year + (1 if today.month == 12 else 0)
                target_month = 1 if today.month == 12 else today.month + 1

        return {
            "intent": "CALENDAR",
            "subtype": subtype,
            "target_year": target_year,
            "target_month": target_month,
        }

    # INVENTORY 또는 ORDER — inventory_order_node로 라우팅 (라우터 JSON은 messages에 추가하지 않음)
    return {
        "intent": intent,
        "subtype": "",
        "target_year": 0,
        "target_month": 0,
    }


async def inventory_order_node(state: AgentState) -> dict:
    """
    TEA 방식 전문 에이전트 노드.
    - 자체 LLM + TOOLS를 보유하여 직접 tool 선택·실행
    - 최대 MAX_TOOL_ROUNDS(3)회 루프로 추가 tool 호출 처리
    - 완료 후 tool_results에 결과 저장, response_node로 이동
    """
    MAX_TOOL_ROUNDS = 5

    client = get_openai_client()
    model = "gpt-4o-mini"

    user_id = state.get("user_id", "")
    user_role = state.get("user_role", "SELLER")
    user_info = state.get("user_info", {})
    company_name = user_info.get("company_name", "미설정")
    user_name = user_info.get("name", "사용자")

    # 역할별 시스템 프롬프트
    # NOTE: AGENT_*_SYSTEM 안에는 BUYER_ROLE_APPENDIX 의 `{seller_name}`, `{name}` 같은
    # LLM 안내용 중괄호와 FEW_SHOT_EXAMPLES 의 JSON 예시가 포함되어 있어 .format() 사용 시
    # KeyError 가 발생한다. 반드시 _render_agent_system() (str.replace 기반) 을 사용한다.
    if user_role == "SELLER":
        agent_system = _render_agent_system(
            AGENT_SELLER_SYSTEM,
            company_name=company_name,
            user_name=user_name,
            user_id=user_id,
        )
    else:
        agent_system = _render_agent_system(
            AGENT_BUYER_SYSTEM,
            company_name=company_name,
            user_name=user_name,
            user_id=user_id,
        )

    # 현재 채팅방/주문 컨텍스트 주입
    _order_id = state.get("order_id")
    _room_id = state.get("room_id")
    if _order_id:
        agent_system += (
            f"\n\n[현재 채팅방 컨텍스트]\n"
            f"- 현재 선택된 주문 ID: {_order_id}\n"
            f"- 협상(submit_counter_offer), 납품일 변경(submit_delivery_date_change) 요청 시 "
            f"이 order_id를 우선 사용하라. get_orders 조회 없이 바로 이 ID로 도구를 호출해도 된다.\n"
            f"- 단, 사용자가 명시적으로 다른 주문을 언급하면 그 주문을 사용한다."
        )
    if _room_id:
        agent_system += f"\n- 현재 채팅방 ID: {_room_id}"

    # inventory_order_node 전용 메시지 구성
    # state["history"] 는 라우터 시스템 프롬프트·라우터 JSON 으로 오염되지 않은 깨끗한
    # user/assistant 대화 히스토리이므로 그대로 주입한다.
    original_user_message = state.get("message", "")
    agent_messages: list[dict[str, Any]] = [
        {"role": "system", "content": agent_system},
        *state.get("history", []),
        {"role": "user", "content": original_user_message},
    ]

    tools_used: list[str] = list(state.get("tools_used", []))
    all_tool_results: list[dict[str, Any]] = []
    new_messages: list[dict[str, Any]] = []

    try:
        for round_idx in range(MAX_TOOL_ROUNDS):
            response = await client.chat.completions.create(
                model=model,
                messages=agent_messages,
                tools=TOOLS,
                # 첫 round는 반드시 도구를 호출하도록 강제 (사전 안내 텍스트만 내고 stop 방지)
                # 두 번째 round 이상은 도구 결과를 받고 자연어로 응답할 수 있도록 auto
                tool_choice="required" if round_idx == 0 and not all_tool_results else "auto",
            )

            choice = response.choices[0]

            print(f"🤖 [AI의 선택] 행동: {choice.finish_reason}")
            print(f"🤖 [AI의 변명] {choice.message.content}")

            if choice.finish_reason == "stop":
                # tool 호출 없이 답변 완료
                final_text = choice.message.content or ""
                fianl_text = final_text.replace("**", "").replace("- [", "[")
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
                    
                    print(f"\n🕵️‍♂️ [ORDER/INVENTORY TOOL]")
                    print(f"🛠️ tool_name = {tool_name}")
                    print(f"📥 tool_input = {tool_input}")
                    print(f"📤 result = {result_content[:1000]}\n")

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

                # 다음 라운드로 계속
                # 주의: MAX_TOOL_ROUNDS 마지막 라운드 분기 제거 —
                # validator_node가 tool_round < 2 기준으로 RETRY를 직접 관리하므로
                # 여기서 강제 break 하면 validator가 발동하기 전에 루프가 끝나 무의미해짐.
                # for 루프 자체(range(MAX_TOOL_ROUNDS))가 자연스럽게 최대 횟수를 제한함.
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
        "tool_round": state.get("tool_round", 0) + 1,
    }


# ─────────────────────────────────────────────
# calendar_data_node — CALENDAR + DATA (조회/등록)
# ─────────────────────────────────────────────

async def calendar_data_node(state: AgentState) -> dict:
    """
    CALENDAR 분기 + subtype=DATA.
    - get_calendar_events / create_calendar_event 두 tool 만 노출
    - 최대 2회 tool 루프
    - tool 결과를 받은 뒤 LLM 이 자연어로 마감 답변 생성
    """
    print("\n🏢 [부서 출입문] 캘린더 'DATA(조회)' 부서에 들어왔습니다!") # 👈 이거 추가
    MAX_TOOL_ROUNDS = 4

    client = get_openai_client()
    model = "gpt-4o-mini"

    user_id = state.get("user_id", "")
    user_info = state.get("user_info", {})
    company_name = user_info.get("company_name", "미설정")
    user_name = user_info.get("name", "사용자")
    today = datetime.now()
    target_year = state.get("target_year") or today.year
    target_month = state.get("target_month") or today.month

    system_prompt = (
        "당신은 fresh link 캘린더 도우미입니다. "
        "사용자의 요청에 맞게 캘린더 일정을 조회하거나 등록하세요. "
        "결과는 한국어로 친절하게, 구체적인 날짜·일정 제목을 담아 답하세요.\n\n"
        f"[사용자 정보]\n"
        f"- 담당자: {user_name}\n"
        f"- 회사명: {company_name}\n"
        f"- user_id: {user_id}\n\n"
        f"[현재 시각]\n"
        f"- 오늘: {today.year}년 {today.month}월 {today.day}일\n"
        f"- 사용자 관심 시점: {target_year}년 {target_month}월\n\n"
        "[원칙]\n"
        "- 일정 조회는 get_calendar_events(user_id, year, month) 호출.\n"
        "- 일정 등록은 create_calendar_event 호출 전 같은 날짜 중복을 get_calendar_events 로 확인.\n"
        "- 일정 변경/수정은 update_calendar_event 호출 (수정할 event_id를 모르면 먼저 조회할 것).\n"
        "- 일정 취소/삭제는 delete_calendar_event 호출 (삭제할 event_id를 모르면 먼저 조회할 것).\n"
        "- (중요) 주문 상태(ORDER) 일정과 배송/납품(DELIVERY/SHIPMENT) 일정은 **서로 다른 일정**입니다.\n"
        "- 주문 상태(ORDER) 일정은 기존 것을 유지하세요(ORDER를 DELIVERY로 바꾸거나 날짜를 옮기지 마세요).\n"
        "- 사용자가 배송/납품 일정을 '추가'하길 원하면, ORDER 일정이 이미 있어도 **create_calendar_event로 새 DELIVERY/SHIPMENT 일정을 생성**하세요.\n"
        "- 사용자가 배송/납품 일정을 '변경/미루기'처럼 기존 배송 일정 자체를 바꾸길 원하면, 해당 DELIVERY/SHIPMENT 이벤트를 찾아 update_calendar_event로 수정하세요.\n"
        "- 일정 변경/수정은 update_calendar_event 호출 (수정할 event_id를 모르면 먼저 조회할 것).\n"
        "- 일정 취소/삭제는 delete_calendar_event 호출 (삭제할 event_id를 모르면 먼저 조회할 것).\n"
        "- (중요) 사용자가 특정 일정을 '삭제'해달라고 하면, get_calendar_events 로 조회한 뒤 해당 일정의 'id'를 찾아 즉시 delete_calendar_event 를 한 번만 실행하세요. 절대 중복해서 조회만 반복하지 마세요.\n"
        "- year/month 가 명시되지 않으면 위의 사용자 관심 시점을 사용.\n"
        "- tool 결과를 그대로 전달하고 임의 추측은 금지.\n"
        "- 응답 형식: 상품명 · 거래처명 · 날짜 · 상태 순으로 자연스럽게 풀어 쓰고, 주문번호는 끝에 작게 부연한다.\n"
        "- (가독성) 응답은 마크다운이 렌더링되지 않는 채팅창에 그대로 노출됩니다. `**굵게**`, `*기울임*` 같은 마크다운 강조와 표(`|`), 코드 블록(```)은 절대 쓰지 마세요. 일정 나열이 필요하면 `-` 불릿이나 줄바꿈으로만 구분하고, 헤더 기호(`#`)도 사용하지 마세요.\n"
        "- (강력 경고) 일정을 삭제할 때는 절대 create_calendar_event로 '삭제된 일정'을 새로 만들지 말고, 반드시 delete_calendar_event 도구를 사용하세요!"
    )

    original_user_message = state.get("message", "")

    # 깨끗한 user/assistant 히스토리를 주입해 캘린더 노드도 멀티턴 맥락을 유지하도록 한다.
    agent_messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        *state.get("history", []),
        {"role": "user", "content": original_user_message},
    ]

    tools_used: list[str] = list(state.get("tools_used", []))
    all_tool_results: list[dict[str, Any]] = []

    try:
        for round_idx in range(MAX_TOOL_ROUNDS):
            # 첫 라운드는 반드시 get_calendar_events를 호출하도록 강제 (LLM이 tool 없이 "없습니다" 답변하는 버그 방지)
            tool_choice = (
                {"type": "function", "function": {"name": "get_calendar_events"}}
                if round_idx == 0
                else "auto"
            )
            response = await client.chat.completions.create(
                model=model,
                messages=agent_messages,
                tools=TOOLS_CALENDAR,
                tool_choice=tool_choice,
            )

            choice = response.choices[0]

            if choice.message.tool_calls:
                tool_calls = choice.message.tool_calls
                
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
                    ]
                }
                agent_messages.append(assistant_msg)

                for tc in tool_calls:
                    tool_name = tc.function.name
                    try:
                        tool_input = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        tool_input = {}

                    # user_id 자동 교정
                    tool_input = _fix_id_params(tool_name, tool_input, user_id)

                    if tool_name not in tools_used:
                        tools_used.append(tool_name)

                    result_content = _execute_tool(tool_name, tool_input)

                    print(f"\n🕵️‍♂️ [CCTV] 캘린더 툴 호출됨: {tool_name}")
                    print(f"🕵️‍♂️ [CCTV] AI 입력값: {tool_input}")
                    print(f"🕵️‍♂️ [CCTV] DB 결과값: {result_content[:300]}...\n")

                    agent_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_content,
                    })

                    try:
                        parsed_result = json.loads(result_content)
                    except json.JSONDecodeError:
                        parsed_result = {"raw": result_content}
                    all_tool_results.append({
                        "tool_name": tool_name,
                        "result": parsed_result,
                    })
                continue

            # 도구 챙겨온 것도 없고, 진짜로 말만 하고 끝날 때
            elif choice.finish_reason == "stop":
                final_text = choice.message.content or ""
                return {
                    "tools_used": tools_used,
                    "tool_results": all_tool_results,
                    "tool_round": state.get("tool_round", 0) + round_idx + 1,
                    "final_response": final_text,
                }
            
            break

        # 루프 한계 도달 — 마지막에 자연어 마감 한 번 더 호출
        wrap_response = await client.chat.completions.create(
            model=model,
            messages=agent_messages + [
                {
                    "role": "user",
                    "content": "위 tool 결과를 바탕으로 한국어로 자연스럽게 마감 답변을 작성해줘.",
                }
            ],
        )
        final_text = wrap_response.choices[0].message.content or "캘린더 처리를 마쳤습니다."

        return {
            "tools_used": tools_used,
            "tool_results": all_tool_results,
            "tool_round": state.get("tool_round", 0) + MAX_TOOL_ROUNDS,
            "final_response": final_text,
        }

    except Exception as e:
        return {
            "tools_used": tools_used,
            "tool_results": all_tool_results,
            "tool_round": state.get("tool_round", 0) + 1,
            "final_response": f"캘린더 요청을 처리하는 중 오류가 발생했습니다: {str(e)}",
        }


# ─────────────────────────────────────────────
# calendar_reason_node — CALENDAR + REASON (추천/추론)
# ─────────────────────────────────────────────

async def calendar_reason_node(state: AgentState) -> dict:
    """
    CALENDAR 분기 + subtype=REASON.
    1. schedule_agent.get_recommendation 으로 구조화된 추천 데이터 획득
    2. has_recommendation=False 면 message 를 그대로 final_response 로 반환 (비용 절감)
    3. has_recommendation=True 면 LLM 1회 호출로 자연어 답변 생성
    """
    print("\n🏢 [부서 출입문] 캘린더 'REASON(추천)' 부서에 들어왔습니다!")
    user_id = state.get("user_id", "")
    user_role = state.get("user_role", "SELLER")
    user_info = state.get("user_info", {})
    company_name = user_info.get("company_name", "미설정")
    today = datetime.now()
    next_year = today.year + (1 if today.month == 12 else 0)
    next_month = 1 if today.month == 12 else today.month + 1
    target_year = state.get("target_year") or next_year
    target_month = state.get("target_month") or next_month

    try:
        recommendation = await schedule_agent.get_recommendation(
            user_id=user_id,
            role=user_role,
            company_name=company_name,
            year=target_year,
            month=target_month,
        )
    except Exception as e:
        return {
            "tools_used": ["schedule_recommend"],
            "tool_results": [],
            "tool_round": state.get("tool_round", 0) + 1,
            "final_response": f"일정 추천 중 오류가 발생했습니다: {str(e)}",
        }

    rec_dump = recommendation.model_dump()

    # 추천이 없으면 LLM 추가 호출 없이 message 그대로 반환
    if not recommendation.has_recommendation:
        return {
            "tools_used": ["schedule_recommend"],
            "tool_results": [{"tool_name": "schedule_recommend", "result": rec_dump}],
            "tool_round": state.get("tool_round", 0) + 1,
            "final_response": recommendation.message or "추천할 일정이 없습니다.",
        }

    # 추천 있음 → LLM 으로 자연어 답변 생성
    client = get_openai_client()
    model = "gpt-4o-mini"

    system_prompt = (
        "당신은 fresh link 캘린더 도우미입니다. "
        "아래는 추천 일정 데이터입니다. 사용자 친화적으로 한국어로 정리해서 답하세요. "
        "추천 일정마다 날짜·상품·수량·이유를 포함해 자연스럽게 풀어 쓰고, "
        "마지막에 한 줄 요약을 덧붙이세요. "
        "응답은 마크다운이 렌더링되지 않는 채팅창에 그대로 노출되므로, "
        "`**굵게**`·`*기울임*` 같은 마크다운 강조와 표(`|`), 코드 블록(```), JSON, 헤더(`#`)는 절대 사용하지 마세요. "
        "구분이 필요하면 줄바꿈이나 `-` 불릿 정도만 쓰세요. "
        "응답 형식: 상품명 · 거래처명 · 날짜 · 상태 순으로 자연스럽게 풀어 쓰고, 주문번호는 끝에 작게 부연한다."
    )
    original_user_message = state.get("message", "")

    # 최근 대화 히스토리(최대 6개 메시지 = 약 3턴) 를 컨텍스트로 활용
    recent_history = state.get("history", [])[-6:]
    history_block = ""
    if recent_history:
        lines = []
        for m in recent_history:
            role_label = "사용자" if m.get("role") == "user" else "AI"
            lines.append(f"- {role_label}: {m.get('content', '')}")
        history_block = "[최근 대화 맥락]\n" + "\n".join(lines) + "\n\n"

    user_message = (
        f"{history_block}"
        f"[원래 사용자 요청]\n{original_user_message}\n\n"
        f"[추천 데이터 (JSON)]\n{json.dumps(rec_dump, ensure_ascii=False)}"
    )

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )
        final_text = response.choices[0].message.content or recommendation.message
    except Exception as e:
        # LLM 실패 시 message 폴백
        final_text = recommendation.message or f"일정 추천 결과 정리 중 오류: {str(e)}"

    return {
        "tools_used": ["schedule_recommend"],
        "tool_results": [{"tool_name": "schedule_recommend", "result": rec_dump}],
        "tool_round": state.get("tool_round", 0) + 1,
        "final_response": final_text,
    }


async def chat_node(state: AgentState) -> dict:
    print("\n🏢 [부서 출입문] 채팅 관리 부서에 들어왔습니다!")
    client = get_openai_client()
    model = "gpt-4o-mini"
    MAX_TOOL_ROUNDS = 6

    user_id = state.get("user_id", "")

    system_prompt = (
        "당신은 fresh link의 채팅 비서입니다.\n"
        "[절대 금지 사항 - 위반 시 시스템 오류 발생]\n"
        "1. 리스트 기호(-, *, 1.) 사용 금지. 문장 처음에 기호를 쓰지 마세요.\n"
        "2. 마크다운 별표(**) 사용 금지. 텍스트를 굵게 만들지 마세요.\n"
        "3. 모든 대화는 한 줄에 하나씩, 생 텍스트로만 작성하세요.\n\n"
        
        "[메시지 전송 및 가공 원칙 - 최우선]\n"
        "1. 명령어 분리: 사용자의 지시어(예: '~라고 물어봐줘', '~라고 전송해')는 절대 그대로 보내지 마세요.\n"
        "2. 비즈니스 문체 변환: 구어체 요청에서 핵심 내용만 추출하여 정중한 한국어 문체로 가공하세요.\n"
        "   - 예: '참치 맛있냐고 물어봐줘' -> '안녕하세요, 보내드린 참치 품질은 어떠신가요? 맛은 괜찮으신지 궁금하여 연락드렸습니다.'\n\n"
        "[동작 로직]\n"
        "- `send_chat_message` 성공 시 즉시 대화를 종료하고 전송 결과만 짧게 보고하세요.\n"
        "- 대화 내역 조회 시에는 반드시 [시각] 이름 : 내용 형식을 지키세요.\n"
        "\n"
        "[출력 예시 - 이대로만 하세요]\n"
        "─── 2026-05-01 ───\n"
        "[오전 04:25] test : 안녕하세요\n"
        "[오전 04:51] test2 : 반갑습니다\n"
        "현재 배송 중인 상태입니다."
                "\n"
        "[채팅방 선택 규칙 - 매우 중요]\n"
        "- 사용자가 특정 상대방 이름과 메시지를 함께 말하면 먼저 get_chat_rooms로 채팅방 목록을 확인하세요.\n"
        "- 같은 상대방과 여러 채팅방이 있으면 일반방(order_id 없음)보다 주문 연결방(order_id 있음)을 우선 고려하세요.\n"
        "- 사용자가 '옥수수', '40kg', '80kg', '방금 주문', '배송 완료', '주문 건'처럼 주문 맥락을 말하면 "
        "get_chat_rooms 결과의 order_number, order_status, product_summary, primary_quantity, item_summary를 기준으로 가장 맞는 주문 채팅방을 선택하세요.\n"
        "- 예: 'test4한테 방금 옥수수 배송 완료됐다고 보내줘'는 test4와의 아무 일반방이 아니라, "
        "옥수수 주문이 연결된 가장 최근 주문 채팅방에 보내야 합니다.\n"
        "- 적절한 주문 채팅방을 확정할 수 없으면 메시지를 보내지 말고, 어떤 주문번호 채팅방에 보낼지 물어보세요.\n"
        "- order_id가 null인 일반 채팅방은 사용자가 주문/상품/배송 맥락을 말하지 않았을 때만 선택하세요.\n"
        "\n"
        "[needs_confirmation 응답 가이드 - 매우 중요]\n"
        "- 필터링 후에도 후보가 2개 이상일 때만 사용하세요. (※ 주의: 무관한 품목 언급 절대 금지)\n"
        "- 사용자가 보내달라는 말 그대로 보내지 말고 명령어와 본문을 분리하고 정중하게 다듬을 것"
        "- send_chat_message 결과가 needs_confirmation: true 이면 메시지는 아직 발송되지 않았습니다. 절대 '보냈습니다', '전송했습니다'라고 답하지 마세요.\n"
        "- 결과의 candidates 배열에는 후보 채팅방마다 room_id, product_name, quantity, unit, status, last_message_at 가 들어 있습니다. 이를 자연스러운 한국어 문장으로 풀어서 사용자에게 어느 방으로 보낼지 골라달라고 물어보세요.\n"
        "- 안내 형식 예시 (※ 주의: 예시의 단어를 그대로 복사하지 말고, 반드시 candidates 내의 실제 데이터로 치환하세요. 별표·표·헤더 금지):\n"
        "  해당 거래처와의 대화방이 여러 건이라 어디로 보낼지 알려주세요.\n"
        "  (1) [실제 상품명] [수량][단위] [상태] — 마지막 메시지 [시간 정보]\n"
        "  (2) [실제 상품명] [수량][단위] [상태] — 마지막 메시지 [시간 정보]\n"
        "  이 메시지를 (1)번에 보낼까요? 다른 곳에 보낼지 알려주세요.\n"
        "- 사용자가 '1번', '[특정 상품명]'처럼 답하면 해당 후보의 room_id 를 직접 지정해 send_chat_message 를 다시 호출하세요. message 본문은 직전 결과의 message_preview 를 그대로 사용합니다.\n"
        "- 사용자가 '둘 다 보내', '전부' 라고 하면 각 후보 room_id 마다 send_chat_message 를 한 번씩 반복 호출해 모두 발송합니다.\n"
        "- 후보가 0개로 나오고 도구가 일반 채팅방으로 fallback 발송에 성공했다면 '주문 연결 채팅방을 찾지 못해 일반 대화방으로 보냈습니다'처럼 자연스럽게 안내하세요. 발송 자체가 실패했다면 어느 거래처의 어느 주문/품목 채팅방인지 사용자에게 더 구체적으로 물어보세요.\n"
        "\n"
        "[도구 실패 시 응답 가이드 — 매우 중요 (환각 방지)]\n"
        "- 도구가 success:false 를 반환하거나 0건을 돌려주면, 사용자에게 실패 사실과 원인을 한 줄로만 명확하게 안내한다. 예: '\\'test3\\' 라는 판매자를 찾을 수 없어요. 정확한 이름을 알려주세요.' / '해당 주문은 이미 확정 상태라 가격 협상이 불가합니다.' / '재고가 부족해요. 다른 수량으로 진행할까요?'\n"
        "- 사용자가 묻지 않은 다른 정보(이전 주문, 다른 거래처, 진행 중 협상 카드, 무관한 품목·수량·금액·날짜)를 컨텍스트 메모리에서 임의로 끌어와 답변에 끼워 넣지 마라. 사용자가 직접 물어본 대상의 에러만 답한다.\n"
        "- 다음 액션 제안은 짧게 하나만 — '다시 시도해 보시겠어요?' / '정확한 이름을 알려주세요' / '다른 수량으로 진행할까요?' 정도. 옵션을 카탈로그처럼 나열하지 마라.\n"
        "- 도구가 실패했는데도 마치 성공한 것처럼 '주문이 접수됐습니다', '메시지를 보냈습니다'라고 답하는 행위 절대 금지. 도구 결과의 success 값을 반드시 확인하고 사실대로 전달.\n"
        "- error 코드(예: 'user_not_found', 'order_not_found', 'invalid_user_id')는 영문 그대로 노출하지 말고 사용자가 이해할 자연체 한국어로 풀어 안내.\n"
        "\n"
        "[주문 목록 조회 가이드 — 자연어 → status_in 매핑 (매우 중요)]\n"
        "- 사용자가 주문 목록을 묻는 발화는 표현이 다양해도 항상 get_orders 의 status_in 다중 상태 파라미터로 정확히 매핑한다. 단일 status 는 사용자가 정말 한 가지 상태만 물었을 때만 쓰고, 그 외에는 status_in 을 우선한다.\n"
        "- '진행 중인 주문' / '활성 주문' / '내 주문' / '오픈된 주문' / '처리 중 주문' → status_in=['QUOTE_REQUESTED','NEGOTIATING','CONFIRMED','PREPARING','SHIPPING']\n"
        "- '완료된 주문' / '끝난 주문' → status_in=['COMPLETED']\n"
        "- '취소된 주문' / '취소건' → status_in=['CANCELLED']\n"
        "- '협상 중 주문' → status_in=['NEGOTIATING'], '확정된 주문' → status_in=['CONFIRMED'], '배송 중 주문' → status_in=['SHIPPING'], '준비 중 주문' → status_in=['PREPARING'], '견적 요청' / '들어온 견적' → status_in=['QUOTE_REQUESTED']\n"
        "- 사용자가 특정 상태를 명시하지 않고 그냥 '주문 보여줘', '주문 목록', '주문 좀 확인해줘'라고 하면 → 진행 중 기본값 status_in=['QUOTE_REQUESTED','NEGOTIATING','CONFIRMED','PREPARING','SHIPPING'] 로 호출 (완료·취소는 사용자가 명시 요청할 때만 포함).\n"
        "\n"
        "[주문 응답 표시 규칙 — 환각 방지 (매우 중요)]\n"
        "- 도구가 반환한 status enum 값을 그대로 자연스러운 한국어로 풀어 사용한다. 임의로 '협상 요청 중', '상태 없음', '검토 중', '보류' 같이 enum 에 없는 표현을 만들어내지 마라.\n"
        "- 한글 매핑 (이 매핑만 사용): QUOTE_REQUESTED→'견적 요청', NEGOTIATING→'협상 중', CONFIRMED→'주문 확정', PREPARING→'준비 중', SHIPPING→'배송 중', COMPLETED→'완료', CANCELLED→'취소'.\n"
        "- 도구가 반환하지 않은 주문은 절대 응답에 포함하지 마라. 컨텍스트 메모리·이전 대화에 옛 주문이 기억나도, 이번 도구 결과 외의 어떤 주문 정보도 출력하지 마라. 사용자가 직접 묻지 않은 다른 주문을 끌어와 함께 답하지 말 것.\n"
        "- 도구 결과가 0건이면 '현재 진행 중인 주문이 없습니다' 또는 '조회된 주문이 없습니다' 정도로만 안내하고, 다른 정보(거래처 추천, 상품 정보, 다른 카테고리 주문)를 늘어놓지 마라. 사용자가 추가로 물어본 뒤에만 다음 단계로 넘어간다.\n"
        "- 마크다운 강조·표·헤더 금지. 자연체 한국어 문장 + 필요 시 '1.' 번호만 사용. 수치(품목·수량·날짜·금액)를 먼저 풀어 제시.\n"
        "\n"
        "[자연어 협상/납품일 → 카드 도구 매핑 (매우 중요)]\n"
        "- 사용자가 가격 협상이나 납품일 변경을 요청하면 일반 send_chat_message 로 보내지 말고 전용 카드 도구를 호출합니다. 카드는 채팅방에 PENDING 상태로 노출돼 상대방이 [수락]/[거절] 버튼을 누를 수 있어 합의 흐름이 명확해집니다.\n"
        "- 가격 제시: '1,300,000원으로 협상해줘', '130만원에 어때요', '단가 깎아줘'처럼 사용자가 가격을 명확히 말하면 submit_counter_offer(user_id, order_id, proposed_total_amount, notes?) 호출. order_id 는 직전 create_order 결과나 get_orders 조회로 확보.\n"
        "- 가격이 빠진 '협상해줘'만 들어오면 도구 호출 X, '어떤 가격으로 제시할까요?'라고 되묻기.\n"
        "- 카운터오퍼 응답: PENDING 카운터오퍼 카드가 있는 채팅방에서 사용자가 '수락해줘'/'OK'/'좋아요' → accept_counter_offer(user_id, order_id, offer_id). '거절해줘'/'안 돼' → reject_counter_offer(user_id, order_id, offer_id). offer_id 는 get_chat_messages 또는 카드 데이터에서 확보.\n"
        "- 납품일 변경: '5월 20일에 받고 싶어', '5/20일로 납품일 변경 요청 보내줘' → submit_delivery_date_change(user_id, order_id, proposed_delivery_date='YYYY-MM-DD', notes?). 날짜가 빠지면 되묻기.\n"
        "- 납품일 응답: PENDING 납품일 변경 카드에 '수락해줘' → accept_delivery_date_change(user_id, order_id, change_id), '거절해줘' → reject_delivery_date_change(user_id, order_id, change_id).\n"
        "- 카드 발송 후에는 '130만원으로 카운터오퍼 카드를 발송했습니다. 상대방이 수락/거절하면 알려드릴게요'처럼 발송 사실과 후속 흐름을 자연체로 안내. 별표/표/헤더 금지.\n"
        "\n"
        "[거래처 등록 / 정기배송 자연어 매핑]\n"
        "- 거래처 등록 발화: '○○를 거래처로 등록해줘', '○○ 추가해줘', '거래처 신청 보내줘'.\n"
        "  - 상대방 UUID 가 정확히 알려진 경우만 request_partner_registration(user_id, target_user_id, note?) 호출.\n"
        "  - 이름/회사명만 알면 request_partner_registration_by_name(user_id, target_name_or_company, note?) 사용. 다중 매칭이 candidates 배열로 돌아오면 send_chat_message 의 needs_confirmation 흐름과 동일하게 후보를 자연어로 풀어서 사용자에게 어느 사람·어느 회사인지 골라달라고 되묻기.\n"
        "- 정기배송 신청: '○○를 정기배송으로 받고 싶어', '매주 ○요일 ○○ 보내줘', '정기배송 요청해줘'.\n"
        "  - 필수 정보: frequency(WEEKLY/BIWEEKLY/MONTHLY), start_date(YYYY-MM-DD), items(품목 리스트).\n"
        "  - 정보가 부족하면 도구 호출 X, '주기를 어떻게 할까요? 매주/격주/매월?', '시작일은 언제로 할까요?'처럼 자연체로 되묻기.\n"
        "  - 모두 갖춰지면 create_subscription_request(user_id, target_user_id, frequency, start_date, items, ...) 호출.\n"
        "  - '이 주문을 정기배송으로 전환'처럼 기존 주문 기반이면 create_subscription_from_order(user_id, order_id, frequency, start_date) 사용.\n"
        "- 정기배송 수락/거절: subscription_id 는 직전 대화에서 찾고, 없으면 get_incoming_subscription_requests 호출해 확보. 절대 사용자에게 ID 물어보지 말 것.\n"
        "- 정기배송 수정 요청('수량 바꿔줘', '조건 바꾸고 싶어' 등): 직접 수정 불가. '현재 요청을 거절하고 새 조건으로 다시 요청을 보내야 합니다. 원하시면 바로 진행해 드릴게요.'라고 자연스럽게 안내하라.\n"
        "\n"
        "[재고 검색 vs 대체 거래처 분리 (환각 방지)]\n"
        "- 사용자가 '참치 찾아줘'라고 하면 find_sellers_by_product 또는 check_stock 으로 product_name='참치'만 정확 검색. 결과 0건이라도 새우/연어 같은 다른 품목을 추천하는 행위는 절대 금지.\n"
        "- 결과 0건이거나 전부 OUT_OF_STOCK 이면 그 사실을 그대로 안내하고 '다른 품목이나 비슷한 카테고리로 대체 거래처를 찾아볼까요?'라고 사용자 동의를 구한 뒤에만 find_alternative_partners 호출.\n"
        "\n"
        "[주문 대상 판매자 식별 절차 (매우 중요)]\n"
        "- create_order 호출 시 seller_id 는 반드시 UUID 형식이어야 한다. 사용자가 'test3', '○○ 농가', '○○ 도매상' 같이 이름/회사명으로 판매자를 지칭하면 아래 우선순위로 UUID 를 확보한다. 이 순서를 절대 어기지 마라.\n"
        "- [1순위 — 직전 대화 컨텍스트 활용 (가장 우선)] 직전 대화에서 find_sellers_by_product 또는 find_buyers_by_product 를 이미 호출해 판매자 목록을 응답으로 받은 경우, 그 응답에 들어 있는 seller_id 를 그대로 사용한다. 사용자가 'test3한테 주문해줘'라고 하면 직전 응답에서 seller_name / seller_company / username 이 'test3'와 매칭되는 항목의 seller_id 를 골라 create_order(seller_id=그_UUID) 호출. 이미 컨텍스트에 UUID 가 있는데 굳이 get_user_profile 을 다시 부르지 마라.\n"
        "- [2순위 — 새로 검색] 직전 컨텍스트에 판매자 목록이 없거나 사용자가 새 품목을 언급하면 find_sellers_by_product(category=품목 카테고리, product_name='○○') 호출. 응답에서 사용자 발화와 매칭되는 후보의 seller_id 를 그대로 사용해 create_order 호출.\n"
        "- [3순위 — get_user_profile 폴백 (위 두 방법이 안 통할 때만)] 사용자가 품목 정보 없이 거래처 이름만 언급해서 find_sellers_by_product 를 못 부르고 직전 컨텍스트에도 매칭되는 판매자 정보가 없는 경우에만 get_user_profile(username='○○') 또는 get_user_profile(company_name='○○') 호출. ILIKE 부분 일치 검색이라 정확히 일치하지 않을 수 있다. 결과 0건이면 '○○ 라는 거래처를 찾을 수 없어요. 정확한 이름이나 회사명을 알려주세요'라고 자연체로 되묻기. 임의 거래처 추천 금지.\n"
        "- [금지] 사용자가 말한 이름 자체를 seller_id 자리에 그대로 넣지 마라(예: seller_id='test3'). 임의 UUID 추측 금지. find_sellers_by_product 응답에 이미 seller_id 가 있는데 굳이 get_user_profile 다시 부르지 마라. 사용자가 묻지 않은 이전 주문/다른 거래처를 끌어와 늘어놓지 마라.\n"
        "- [다중 매칭] 1순위 또는 2순위 결과에서 사용자 발화와 매칭되는 후보가 2명 이상이면 도구 호출하지 말고 'test 농가와 test3 도매상 중 어느 쪽으로 주문할까요?'처럼 자연체로 되묻기. 사용자 답변 받기 전에는 create_order 호출 금지.\n"
        "\n"
        "[구매자 주문/견적 생성 가이드]\n"
        "- 구매자가 '○○ 주문해줘', '○○ 발주 넣어줘'처럼 명확한 주문 의도를 표현하면 즉시 create_order 를 호출한다. 단, 백엔드는 더 이상 가격 일치만으로 자동 확정하지 않는다. 모든 신규 주문은 QUOTE_REQUESTED 견적 상태로 시작해 판매자 검토를 기다리며, 가격이 시세보다 낮을 때만 NEGOTIATING + 카운터오퍼 카드 흐름으로 자동 분기된다. LLM 은 단가 비교를 직접 흉내 내지 말고 백엔드 분기를 그대로 신뢰한다.\n"
        "- 납품일 + 수량 명시 발화 ('망고 2kg 5월 20일에 받게 주문해줘'): check_stock 또는 find_sellers_by_product 로 price_per_unit 을 확보해 unit_price 에 채우고, 사용자가 말한 날짜를 'YYYY-MM-DD' 로 정규화해 delivery_date 에 넣은 뒤 create_order 호출. 가격 일치면 QUOTE_REQUESTED, 낮으면 NEGOTIATING.\n"
        "- 가격까지 명시 발화 ('13만원에 망고 2kg 5/20일 받기로 주문해줘'): 명시된 가격을 그대로 unit_price 로, 날짜를 그대로 delivery_date 로 넣어 create_order 호출. '단가가 낮은데 보낼까요?' 되묻기 금지.\n"
        "- 납품일 빠진 발화 ('망고 2kg 주문해줘'): create_order 호출 금지. 먼저 사용자에게 '납품일은 언제로 할까요? (예: 5월 20일)' 라고 자연체로 되묻고, 정확한 날짜를 받기 전까지는 어떤 경우에도 호출하지 마라. '오늘', '내일' 같은 모호한 표현을 LLM 임의로 날짜로 바꿔치지 마라.\n"
        "- 협상 명시 발화 ('그 가격 좀 깎아줘', '할인 받고 싶어', '협상해줘'): create_order 가 아니라 submit_counter_offer 사용. PENDING/NEGOTIATING 주문이 이미 있을 때만 가능. 가격이 함께 언급된 새 주문이면 납품일까지 받아낸 뒤 그 가격으로 create_order 호출해 자동 협상 분기에 태운다.\n"
        "- 단가/납품일 필수 확보: create_order 호출 시 unit_price, delivery_date 둘 다 비어있으면 안 된다. unit_price 없으면 조회 도구로 확보, delivery_date 없으면 사용자에게 받아내기 전까지 호출 금지. '단가를 모르겠어요' 답변 금지.\n"
        "- 결과 응답 표현 (별표/표/헤더 금지, 자연체 한국어, 절대 '주문이 확정됐습니다'라고 말하지 말 것 — 판매자 수락 전에는 확정이 아니다):\n"
        "  - status=QUOTE_REQUESTED (정상 신규 견적): '○○ ○단위 주문 견적을 판매자에게 보냈습니다. 가격 ₩○○, 납품일 ○월 ○일. 판매자가 수락하면 알려드릴게요.' 형식.\n"
        "  - status=NEGOTIATING (negotiating=true, 가격 협상 시작): '○○ ○단위 주문에 대해 ₩○○으로 협상가를 제시했습니다. 채팅방에 카드를 발송했고, 판매자가 수락/거절하면 알려드릴게요.' 형식.\n"
        "  - 그 외 상태: '주문이 접수됐고 판매자 확인을 기다리고 있습니다.' 형식.\n"
        "- 납품일 변경: 주문 후 사용자가 '납품일 ○월 ○일로 바꿔줘' 라고 하면 submit_delivery_date_change 를 호출. 해당 주문이 아직 QUOTE_REQUESTED 단계면 판매자 검토 중이므로 '판매자가 견적을 검토하는 중이라 변경 요청도 함께 전달했습니다' 정도로 자연스럽게 덧붙여라.\n"
    )

    agent_messages = [
        {"role": "system", "content": system_prompt},
        *state.get("history", []),
        {"role": "user", "content": state.get("message", "")},
    ]

    tools_used = list(state.get("tools_used", []))
    
    for round_idx in range(MAX_TOOL_ROUNDS):
        response = await client.chat.completions.create(
            model=model,
            messages=agent_messages,
            tools=TOOLS_CHAT,
            tool_choice="auto"  # 👈 AI가 스스로 판단하게 맡깁니다!
        )

        choice = response.choices[0]

        if choice.message.tool_calls:
            agent_messages.append(choice.message)
            
            for tc in choice.message.tool_calls:
                tool_name = tc.function.name
                tool_input = json.loads(tc.function.arguments)
                tool_input = _fix_id_params(tool_name, tool_input, user_id)
                
                if tool_name not in tools_used:
                    tools_used.append(tool_name)
                
                result_content = _execute_tool(tool_name, tool_input)
                
                if tool_name == "send_chat_message" and '"success": true' in result_content.lower():
                    return {
                        "tools_used": tools_used,
                        "final_response": "메시지를 성공적으로 전송했습니다!"
                    }
            
                # 🕵️‍♂️ CCTV 로그 출력
                print(f"🕵️‍♂️ [CCTV] {tool_name} 호출 결과: {result_content[:100]}")
                
                agent_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_content
                })
            continue 
        
        content = (choice.message.content or "").strip()
        final_text = content.replace("**", "").replace("- [", "[")
        return {
            "tools_used": tools_used,
            "final_response": final_text or "요청을 처리하지 못했습니다. 다시 한 번 말씀해 주세요.",
        }
    
    return {"final_response": "채팅 처리를 마무리하지 못했습니다. 다시 시도해 주세요!"}

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

    # 비즈니스 에러(이미 처리됨, 정보 부족 등)는 실패가 아니라 AI가 자연어로 안내하면 되는 정상 케이스
    EXPECTED_ERRORS = {
        "already_partner", "already_exists", "self_subscription_not_allowed",
        "needs_clarification", "partner_not_found", "missing_room_or_partner",
        "invalid_user_id", "self_chat_not_allowed",
        "invalid_order_id", "order_not_found", "not_participant",
    }
    if isinstance(result_data, dict) and result_data.get("success") is False:
        error_code = result_data.get("error", "")
        http_code = result_data.get("code", 0)
        # HTTP 400 비즈니스 오류 (상태 불일치 등)는 AI가 자연어로 설명할 수 있는 정상 케이스
        if (error_code in EXPECTED_ERRORS
                or http_code == 400
                or result_data.get("needs_clarification")
                or result_data.get("needs_confirmation")):
            return {"validation_status": "PASSED"}
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
    original_message = state.get("message", "")
    tools_used = state.get("tools_used", [])
    intent = state.get("intent", "")

    status_change_keywords = [
        "확정", "주문확정",
        "출고", "배송 보냈", "배송 시작",
        "배송중", "배송 중",
        "납품 완료", "배송 완료 처리", "완료 처리"
    ]

    message_send_patterns = [
        "보내줘", "전송해줘", "답장해줘", "말해줘", "알려줘"
    ]

    # CHAT 요청에서는 상태 변경 방어 로직을 적용하지 않는다.
    # 예: "test4한테 배송 완료됐다고 보내줘"는 상태 변경이 아니라 메시지 전송이다.
    if intent != "CHAT":
        is_status_change_request = any(k in original_message for k in status_change_keywords)
        is_message_send_request = any(p in original_message for p in message_send_patterns)

        if is_status_change_request and not is_message_send_request:
            if "update_order_status" not in tools_used:
                return {
                    "final_response": (
                        "주문 상태 변경 요청으로 이해했지만, 실제 상태 변경 도구가 실행되지 않았습니다. "
                        "주문번호를 확인해서 다시 처리해 주세요."
                    )
                }
            
    # orchestrator_node 또는 inventory_order_node에서 이미 답변이 생성된 경우
    if state.get("final_response"):
        return {}

    client = get_openai_client()
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

    # tool 결과 단락회로 정책 (MEDIUM 7 비용 최적화):
    # - 재고 부족 (LOW_STOCK / OUT_OF_STOCK) → LLM 통과 (타협안·대체거래처 자연어 생성)
    # - success=False 인데 명확한 error/message 가 있으면 → 그 텍스트 그대로 반환 (LLM 우회)
    # - success=True 정상 결과 → LLM 통과 (자연어 응답 생성)
    def _is_stock_shortage(result: dict) -> bool:
        """재고 부족 판정: product 필드 내 status 또는 stock_quantity 기반"""
        product = result.get("product") or {}
        if isinstance(product, dict):
            if product.get("status") in ("LOW_STOCK", "OUT_OF_STOCK"):
                return True
        return False

    if tool_results_parsed:
        last = tool_results_parsed[-1]
        if isinstance(last, dict):
            # 1) 재고 부족 → 무조건 LLM 통과 (타협안 생성)
            if _is_stock_shortage(last):
                pass  # 아래 LLM 요약으로 진행
            # 2) 실패 결과 → LLM이 자연어로 안내하도록 통과 (에러 코드 raw 반환 금지)
                # 명확한 텍스트 없으면 LLM 통과
            # 3) success=True 정상 결과 → LLM 통과 (자연어 생성)
            #    기존 last.get("message") 단락회로는 제거 — 자연어 응답이 더 적절

    # 직접 추출 불가능한 경우만 LLM으로 요약
    # response_node는 라우터 프롬프트가 아닌 역할별 에이전트 프롬프트를 사용
    user_role = state.get("user_role", "SELLER")
    user_info = state.get("user_info", {})
    user_id = state.get("user_id", "")
    if user_role == "SELLER":
        agent_sys = _render_agent_system(
            AGENT_SELLER_SYSTEM,
            company_name=user_info.get("company_name", "미설정"),
            user_name=user_info.get("name", "사용자"),
            user_id=user_id,
        )
    else:
        agent_sys = _render_agent_system(
            AGENT_BUYER_SYSTEM,
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
                f"JSON이나 코드 블록 형식으로 출력하지 말고 일반 텍스트로만 답변해. "
                f"마크다운 강조(`**굵게**`, `*기울임*`)와 표(`|`), 헤더(`#`)도 사용하지 마. "
                f"채팅창에 그대로 보이는 환경이라 별표가 글자로 노출돼.\n\n"
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
    - CALENDAR + DATA → calendar_data_node
    - CALENDAR + REASON → calendar_reason_node
    - GENERAL → response_node (orchestrator가 직접 답변 완료)
    """
    intent = state.get("intent", "GENERAL")
    if intent in ("INVENTORY", "ORDER"):
        return "inventory_order_node"
    if intent == "CALENDAR":
        subtype = state.get("subtype", "DATA")
        if subtype == "REASON":
            return "calendar_reason_node"
        return "calendar_data_node"
    if intent == "CHAT":
        return "chat_node"
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
    graph.add_node("calendar_data_node", calendar_data_node)
    graph.add_node("calendar_reason_node", calendar_reason_node)
    graph.add_node("chat_node", chat_node)
    graph.add_node("validator_node", validator_node)
    graph.add_node("response_node", response_node)

    graph.set_entry_point("orchestrator_node")

    graph.add_conditional_edges(
        "orchestrator_node",
        route_after_orchestrator,
        {
            "inventory_order_node": "inventory_order_node",
            "calendar_data_node": "calendar_data_node",
            "calendar_reason_node": "calendar_reason_node",
            "chat_node": "chat_node",
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
    # 캘린더 노드들은 자체적으로 final_response 를 채우므로 바로 response_node 로
    graph.add_edge("calendar_data_node", "response_node")
    graph.add_edge("calendar_reason_node", "response_node")
    graph.add_edge("chat_node", "response_node")
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
        order_id: Optional[str] = None,
        room_id: Optional[str] = None,
    ) -> dict:
        """
        오케스트레이터 메인 실행 메서드.

        Args:
            user_message: 사용자가 입력한 질문/요청
            user_id: 현재 로그인한 사용자 UUID
            role: 사용자 역할 (SELLER 또는 BUYER)
            user_info: 사용자 정보 dict (name, company_name 포함)
            history: 이전 대화 메시지 목록
            order_id: 현재 채팅방에 연결된 주문 ID (협상/납품일 도구 기본값)
            room_id: 현재 채팅방 ID

        Returns:
            {
                "response": "모델의 최종 텍스트 답변",
                "tools_used": ["실행된 tool 이름 목록"]
            }
        """
        # orchestrator_node는 라우터 전용 시스템 프롬프트 사용
        # 매 호출마다 현재 시각을 반영하기 위해 _build_router_system() 으로 새로 빌드
        router_system = _build_router_system()

        # 깨끗한 history (user/assistant 만, 라우터 JSON 등 노이즈 제거된 상태)
        clean_history = [
            m for m in history if m.get("role") in ("user", "assistant")
        ]

        initial_state: AgentState = {
            "user_id": user_id,
            "user_role": role,
            "user_info": user_info,
            "message": user_message,
            "intent": "GENERAL",
            "subtype": "",
            "target_year": 0,
            "target_month": 0,
            # history: 노드들이 직접 사용하는 깨끗한 대화 히스토리
            "history": clean_history,
            # messages: 라우터(orchestrator_node) 전용 — system + 최근 1턴 + 현재 user
            # 히스토리 전체를 주입하면 이전 GENERAL 응답 패턴을 학습해 캘린더 요청도 GENERAL로 분류하는 버그 발생
            "messages": [
                {"role": "system", "content": router_system},
                *clean_history[-2:],
                {"role": "user", "content": user_message},
            ],
            "tool_results": [],
            "tools_used": [],
            "final_response": "",
            "tool_round": 0,
            "validation_status": "",
            "manual_review": False,
            "order_id": order_id,
            "room_id": room_id,
        }

        # LangGraph 실행
        try:
            final_state = await _compiled_graph.ainvoke(initial_state)
            return {
                "response": final_state.get("final_response") or "응답을 생성하지 못했습니다.",
                "tools_used": final_state.get("tools_used", []),
                "manual_review": final_state.get("manual_review", False),
            }
        except Exception as e:
            return {
                "response": f"요청을 처리하는 중 오류가 발생했습니다: {str(e)}",
                "tools_used": [],
                "manual_review": False,
            }


# 싱글턴 인스턴스 — 앱 전체에서 하나만 사용
agent_orchestrator = AgentOrchestrator()