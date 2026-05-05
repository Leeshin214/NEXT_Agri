"""orchestrator.response_node 의 fab(날조) 감지 게이트 단위 테스트.

회귀 배경 (2026-05-04):
- 사용자: "캘린더 5월 일정 보여줘"
- AI: "주문 처리 중 문제가 발생했습니다. 다시 말씀해 주시면 처리해 드리겠습니다."

원인:
- response_node 의 _order_fab_markers 검사가 intent 와 무관하게 모든 응답에 적용됐다.
- calendar_data_node 가 정상 실행해 final_response 에 자연어로 "ORD-XXXX"
  (주문번호) 를 포함하면 → fab 마커 ('ORD-') 를 트리거 → fab fallback 메시지로 교체.
- inventory_order_node 의 가짜 주문 응답을 막기 위한 검사가 캘린더 정상 응답까지
  잘못 차단한 것.

수정:
- fab 검사를 `intent in ("INVENTORY", "ORDER")` 게이트 안에 넣었다.
- CALENDAR / CHAT / GENERAL 응답은 fab 검사를 거치지 않는다 (해당 노드들은 자체적으로
  도구 호출/검증을 완료하므로 응답에 ORD- 토큰이 있어도 정상).

검증 시나리오:
1. CALENDAR + ORD- 토큰 → fab 미작동 (응답 보존)
2. ORDER + ORD- 토큰 + create_order 미실행 → fab 작동 (정상 안전망)
3. ORDER + ORD- 토큰 + create_order 실행됨 → fab 미작동 (정상 응답)
4. ORDER + ORD- 토큰 + get_orders 만 (조회) → fab 미작동 (정상 조회)
5. CHAT + ORD- 토큰 → fab 미작동
6. INVENTORY + 납품일 변경 fab 마커 + submit_delivery_date_change 미실행 → fab 작동
"""
from __future__ import annotations

import asyncio

import pytest

from app.services.orchestrator import response_node


def _state(*, intent: str, final_response: str, tools_used: list[str]) -> dict:
    """response_node 가 요구하는 최소 state 형태."""
    return {
        "message": "x",
        "tools_used": tools_used,
        "tool_results": [],
        "intent": intent,
        "final_response": final_response,
        "user_role": "BUYER",
        "user_info": {"name": "tester", "company_name": "테스트"},
        "user_id": "00000000-0000-0000-0000-000000000001",
        "messages": [],
    }


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


def test_calendar_response_with_order_number_not_treated_as_fab():
    """CALENDAR 응답에 'ORD-XXXX' 가 포함되어도 fab fallback 으로 바뀌지 않는다.

    이것이 본 회귀의 회복 시나리오. 사용자의 '5월 일정 보여줘' → calendar_data_node
    가 get_calendar_events 호출 → 응답에 주문번호 풀어 쓴 자연어 → 보존되어야 함.
    """
    state = _state(
        intent="CALENDAR",
        final_response=(
            "5월 일정 안내드립니다.\n"
            "- 옥수수 80kg 배송 · A마트 · 5월 15일 · 배송중. (주문번호: ORD-20260515-0001)"
        ),
        tools_used=["get_calendar_events"],
    )
    result = _run(response_node(state))
    # 1. fab fallback 메시지로 교체되지 않아야 함
    assert "주문 처리 중 문제" not in (result.get("final_response") or "")
    # 2. CALENDAR 노드의 final_response 가 그대로 보존되도록 빈 dict 반환
    #    (response_node 의 short-circuit: state.get('final_response') 가 있으면 {} 반환)
    assert result == {}


def test_chat_response_with_order_number_not_treated_as_fab():
    """CHAT 응답에 'ORD-XXXX' 가 포함되어도 fab 으로 인식되지 않는다."""
    state = _state(
        intent="CHAT",
        final_response="주문번호는 ORD-20260515-0001 인 거 보내드렸습니다.",
        tools_used=["send_chat_message"],
    )
    result = _run(response_node(state))
    assert "주문 처리 중 문제" not in (result.get("final_response") or "")


def test_order_intent_fab_blocks_when_create_order_missing():
    """ORDER intent + 'ORD-' 마커 + create_order 미실행 → fab fallback 작동.

    이것이 fab 안전망의 본래 목적. 게이트 추가 후에도 정상 작동해야 함.
    """
    state = _state(
        intent="ORDER",
        final_response="망고 2kg 주문이 접수되었습니다. 주문번호는 ORD-20260504-0001 입니다.",
        tools_used=[],  # create_order 도, get_orders 도 없음 → 날조
    )
    result = _run(response_node(state))
    assert result.get("final_response", "").startswith("주문 처리 중 문제가 발생")


def test_order_intent_with_create_order_passes():
    """ORDER intent + 'ORD-' 마커 + create_order 실행 → fab 미작동 (정상 응답)."""
    state = _state(
        intent="ORDER",
        final_response="망고 2kg 주문이 접수되었습니다. 주문번호는 ORD-20260504-0001 입니다.",
        tools_used=["create_order"],
    )
    result = _run(response_node(state))
    assert "주문 처리 중 문제" not in (result.get("final_response") or "")
    # short-circuit 으로 final_response 보존
    assert result == {}


def test_order_intent_with_get_orders_only_passes():
    """ORDER intent + 'ORD-' 마커 + get_orders 만 (조회 케이스) → fab 미작동.

    사용자가 '내 주문 보여줘' 하면 get_orders 만 실행되고 응답에 ORD- 가
    들어가는데, 이건 날조가 아니라 조회 결과이므로 보존되어야 함.
    """
    state = _state(
        intent="ORDER",
        final_response="진행 중인 주문 1건입니다. 옥수수 80kg 배송중. 주문번호 ORD-20260504-0001.",
        tools_used=["get_orders"],
    )
    result = _run(response_node(state))
    assert "주문 처리 중 문제" not in (result.get("final_response") or "")
    assert result == {}


def test_inventory_intent_delivery_change_fab_blocks():
    """INVENTORY intent + 납품일 변경 fab 마커 + 도구 미실행 → fab 작동."""
    state = _state(
        intent="INVENTORY",
        final_response="납품일 변경 요청이 전송되었습니다.",
        tools_used=[],
    )
    result = _run(response_node(state))
    assert result.get("final_response", "").startswith("납품일 변경 요청 처리 중 문제")


def test_calendar_intent_does_not_apply_delivery_fab():
    """CALENDAR intent 응답이 우연히 납품일 변경 fab 마커를 포함해도 차단하지 않는다.

    예: 사용자 일정 설명에 '변경 요청을 보냈습니다' 비슷한 문구가 있더라도 CALENDAR
    노드가 직접 생성한 답이라 fab 가 아님.
    """
    state = _state(
        intent="CALENDAR",
        final_response="변경 요청을 보냈습니다. (캘린더 일정 메모로만 기록)",
        tools_used=["get_calendar_events", "update_calendar_event"],
    )
    result = _run(response_node(state))
    assert "납품일 변경 요청 처리 중 문제" not in (result.get("final_response") or "")
