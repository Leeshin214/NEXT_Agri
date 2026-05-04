"""카운터오퍼 / 납품일 변경 (Negotiation) 도구.

원본: backend/app/services/agent_tools.py 의 negotiation 섹션 (단계 1: 본문 그대로 복사 + @tool 데코레이터 추가).
agent_tools.py 의 함수는 단계 2 에서 shim 으로 변환된다.

모든 도구는 동기(sync) 함수이며, 내부적으로 별도 thread + 새 event loop 를
만들어 order_service 의 async 메서드를 호출한다 (orchestrator._execute_tool 이
이미 async 컨텍스트 안에서 sync 호출되기 때문에 asyncio.run() 직접 사용 시
RuntimeError 위험 — concurrent.futures + asyncio.new_event_loop 패턴이 안전).

service 메서드가 HTTPException 등을 raise 하면 도구는
{"success": False, "error": ..., "code": <status>} 형태로 반환하여
다른 agent_tools 함수와 일관된 에러 포맷 유지.

user 인자는 {"id": <user_uuid>} dict 만 만들어 넘긴다 (service 가 user["id"] 만 사용).

Cross-domain 의존:
- _UUID_PATTERN, _run_async_in_thread, _service_error_payload
  : agent_tools.py 의 cross-domain helper (단계 2 에서 _shared.py 로 이동 예정).
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from .._registry import tool


@tool(
    name="submit_counter_offer",
    description=(
        "구매자 또는 판매자가 채팅방에서 가격 제시 카드를 발송한다. "
        "사용자가 '1300000원으로 협상해줘', '13만원에 어때요', '가격 좀 깎아주세요', "
        "'좀 더 싸게 안 돼?', '단가 협상하고 싶어', '가격 제시할게' 같이 가격 협상을 시도하면 "
        "평문 채팅 메시지(send_chat_message)가 아니라 반드시 이 도구로 호출하라. "
        "발송 즉시 상대방 채팅창에 수락/거절 버튼이 있는 PENDING 카드가 노출된다. "
        "상태 확인 없이 즉시 호출하라 — 허용 여부는 서버가 검증하며, 불가한 경우 서버가 에러를 반환한다. "
        "이전 PENDING 카운터오퍼는 자동으로 SUPERSEDED 처리되므로 안전하게 새로 제시 가능."
    ),
    parameters={
        "type": "object",
        "properties": {
            "user_id": {
                "type": "string",
                "description": "제시자(현재 로그인 사용자) UUID. 서버에서 강제 주입.",
            },
            "order_id": {
                "type": "string",
                "description": (
                    "협상가 제시 대상 주문의 UUID. status 가 QUOTE_REQUESTED 또는 NEGOTIATING 인 주문만 가능 — "
                    "CONFIRMED 이후 상태는 백엔드가 거절한다. "
                    "사용자 발화로 어떤 주문인지 모호하면 먼저 get_orders(status_in=['QUOTE_REQUESTED','NEGOTIATING']) 로 후보를 추출한 뒤, "
                    "후보가 정확히 1개면 그 id 를 그대로 사용하고, 2개 이상이면 사용자에게 어느 주문인지 되물은 뒤 사용. "
                    "0개면 '협상 가능한 주문이 없습니다' 안내. 절대 사용자에게 UUID 를 직접 묻거나 임의로 한 후보를 추측 선택하지 마라."
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
    groups=("inventory_order",),
    int_fields=frozenset({"proposed_total_amount"}),
)
def submit_counter_offer(
    user_id: str = "",
    order_id: str = "",
    proposed_total_amount: int = 0,
    notes: Optional[str] = None,
) -> dict:
    """주문 카운터오퍼(가격 제시) 발송. 채팅방에 PENDING 상태 카드로 자동 노출됨.

    LLM 자연어 트리거 예: "1300000원으로 협상해줘", "13만원에 어때요", "가격 좀 깎아주세요".
    호출 즉시 상대방 채팅창에 수락/거절 버튼이 있는 COUNTER_OFFER 메시지 카드가 발송된다.
    이전 PENDING 카운터오퍼는 자동 SUPERSEDED 처리.

    파라미터:
      - user_id: 제시자 UUID (orchestrator._fix_id_params 가 항상 현재 user_id 강제 주입)
      - order_id: 대상 주문 UUID (필수). QUOTE_REQUESTED 또는 NEGOTIATING 상태여야 함.
      - proposed_total_amount: 제시 총 금액 (KRW 정수, 양수)
      - notes: 협상 메모 (선택)

    반환:
      성공: {success: True, offer: {...negotiation_history row...}}
      실패: {success: False, error: ..., code: <http_status>}
    """
    from app.services.agent_tools import (
        _UUID_PATTERN,
        _run_async_in_thread,
        _service_error_payload,
    )

    if not user_id or not _UUID_PATTERN.match(str(user_id)):
        return {"success": False, "error": "invalid_user_id"}
    if not order_id or not _UUID_PATTERN.match(str(order_id)):
        return {"success": False, "error": "invalid_order_id"}
    try:
        amount_int = int(proposed_total_amount)
    except (TypeError, ValueError):
        return {"success": False, "error": "proposed_total_amount must be an integer"}
    if amount_int <= 0:
        return {"success": False, "error": "proposed_total_amount must be > 0"}

    from app.services.order_service import order_service

    payload: dict = {"proposed_total_amount": amount_int}
    if notes:
        payload["notes"] = notes
    user_dict = {"id": str(user_id)}

    try:
        offer = _run_async_in_thread(
            lambda: order_service.submit_counter_offer(
                order_id=order_id, payload=payload, user=user_dict
            )
        )
        return {"success": True, "offer": offer}
    except Exception as e:
        return _service_error_payload(e)


@tool(
    name="accept_counter_offer",
    description=(
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
    parameters={
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
    groups=("inventory_order",),
)
def accept_counter_offer(
    user_id: str = "",
    order_id: str = "",
    offer_id: str = "",
) -> dict:
    """상대방의 PENDING 카운터오퍼를 수락. orders.total_amount, order_items 갱신 + 채팅 OFFER_ACCEPTED 카드 발송.

    LLM 자연어 트리거 예: "수락해줘", "OK", "그 가격으로 진행", "좋아요 그렇게 합시다".
    채팅방의 PENDING 카운터오퍼 카드 status 도 ACCEPTED 로 자동 동기화되어
    프론트의 수락/거절 버튼이 즉시 사라진다. 본인이 제시한 카운터오퍼는 수락 불가 (상대방만).

    반환:
      성공: {success: True, offer: {...accepted negotiation_history row...}}
      실패: {success: False, error: ..., code: <http_status>}
    """
    from app.services.agent_tools import (
        _UUID_PATTERN,
        _run_async_in_thread,
        _service_error_payload,
    )

    if not user_id or not _UUID_PATTERN.match(str(user_id)):
        return {"success": False, "error": "invalid_user_id"}
    if not order_id or not _UUID_PATTERN.match(str(order_id)):
        return {"success": False, "error": "invalid_order_id"}
    if not offer_id or not _UUID_PATTERN.match(str(offer_id)):
        return {"success": False, "error": "invalid_offer_id"}

    from app.services.order_service import order_service
    user_dict = {"id": str(user_id)}

    try:
        offer = _run_async_in_thread(
            lambda: order_service.accept_counter_offer(
                order_id=order_id, offer_id=offer_id, user=user_dict
            )
        )
        return {"success": True, "offer": offer}
    except Exception as e:
        return _service_error_payload(e)


@tool(
    name="reject_counter_offer",
    description=(
        "상대방이 제시한 PENDING 가격 카드를 거절한다. "
        "사용자가 '거절해줘', '안 돼', '그 가격은 어렵습니다', '거절', "
        "'그 가격은 못 받아' 같은 자연어로 지시하면 호출하라. "
        "거절 즉시 채팅방의 PENDING 카드 상태가 REJECTED 로 자동 동기화되어 "
        "수락/거절 버튼이 사라지고 거절 시스템 메시지가 발송된다. "
        "본인이 제시한 카운터오퍼는 거절 불가 (상대방만)."
    ),
    parameters={
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
    groups=("inventory_order",),
)
def reject_counter_offer(
    user_id: str = "",
    order_id: str = "",
    offer_id: str = "",
) -> dict:
    """상대방의 PENDING 카운터오퍼를 거절. 채팅 OFFER_REJECTED 카드 발송.

    LLM 자연어 트리거 예: "거절해줘", "안 돼", "그 가격은 어렵습니다", "거절".
    채팅방의 PENDING 카드 status 도 REJECTED 로 자동 동기화. 본인 제시 카운터오퍼는 거절 불가.

    반환:
      성공: {success: True, offer: {...rejected negotiation_history row...}}
      실패: {success: False, error: ..., code: <http_status>}
    """
    from app.services.agent_tools import (
        _UUID_PATTERN,
        _run_async_in_thread,
        _service_error_payload,
    )

    if not user_id or not _UUID_PATTERN.match(str(user_id)):
        return {"success": False, "error": "invalid_user_id"}
    if not order_id or not _UUID_PATTERN.match(str(order_id)):
        return {"success": False, "error": "invalid_order_id"}
    if not offer_id or not _UUID_PATTERN.match(str(offer_id)):
        return {"success": False, "error": "invalid_offer_id"}

    from app.services.order_service import order_service
    user_dict = {"id": str(user_id)}

    try:
        offer = _run_async_in_thread(
            lambda: order_service.reject_counter_offer(
                order_id=order_id, offer_id=offer_id, user=user_dict
            )
        )
        return {"success": True, "offer": offer}
    except Exception as e:
        return _service_error_payload(e)


@tool(
    name="submit_delivery_date_change",
    description=(
        "납품일 변경 요청 카드를 채팅방에 발송한다. "
        "사용자가 '납품일 5월 10일로 바꿔줘', '배송일을 다음 주 월요일로', "
        "'납기 변경 요청', '납품 날짜 좀 미뤄줘', '내일 받을 수 있게 변경' 같이 "
        "납품/배송 날짜 변경을 요청하면 평문 채팅 메시지가 아니라 반드시 이 도구로 호출하라. "
        "발송 즉시 상대방 채팅창에 수락/거절 버튼이 있는 PENDING 카드가 노출된다. "
        "주문 상태가 QUOTE_REQUESTED, NEGOTIATING, CONFIRMED 일 때만 가능 — "
        "PREPARING 이상은 출하 준비 중이므로 차단된다. "
        "proposed_delivery_date 는 KST 기준 오늘 이상이어야 함 (과거 날짜 거부)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "user_id": {
                "type": "string",
                "description": "요청자(현재 로그인 사용자) UUID. 서버에서 강제 주입.",
            },
            "order_id": {
                "type": "string",
                "description": (
                    "납품일 변경 대상 주문의 UUID. status 가 QUOTE_REQUESTED, NEGOTIATING, CONFIRMED 인 주문만 가능 — "
                    "PREPARING 이후 상태는 출하 준비 단계라 백엔드가 거절한다. "
                    "사용자 발화로 어떤 주문인지 모호하면 먼저 get_orders(status_in=['QUOTE_REQUESTED','NEGOTIATING','CONFIRMED']) 로 후보를 추출한 뒤, "
                    "후보가 정확히 1개면 그 id 를 그대로 사용하고, 2개 이상이면 사용자에게 어느 주문인지 되물은 뒤 사용. "
                    "0개면 '납품일 변경 가능한 주문이 없습니다' 안내. 절대 사용자에게 UUID 를 직접 묻거나 임의로 한 후보를 추측 선택하지 마라."
                ),
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
    groups=("inventory_order",),
)
def submit_delivery_date_change(
    user_id: str = "",
    order_id: str = "",
    proposed_delivery_date: str = "",
    notes: Optional[str] = None,
) -> dict:
    """납품일 변경 요청 발송. 채팅방에 PENDING 카드로 자동 노출됨.

    LLM 자연어 트리거 예: "납품일 5월 10일로 바꿔줘", "배송일 변경 요청", "납기 다음 주 월요일로".
    호출 즉시 상대방 채팅창에 수락/거절 버튼이 있는 DELIVERY_DATE_CHANGE 메시지 카드가 발송된다.
    이전 PENDING 변경 요청은 자동 SUPERSEDED 처리.

    파라미터:
      - user_id: 요청자 UUID
      - order_id: 대상 주문 UUID. QUOTE_REQUESTED/NEGOTIATING/CONFIRMED 상태여야 함
                  (PREPARING 이상은 출하 준비 중이므로 차단됨).
      - proposed_delivery_date: 변경 희망일 (ISO YYYY-MM-DD). 오늘 이상이어야 함 (router 검증과 동일 정책).
      - notes: 변경 사유/메모 (선택)

    반환:
      성공: {success: True, change: {...delivery_date_change_history row...}}
      실패: {success: False, error: ..., code: <http_status>}
    """
    from app.services.agent_tools import (
        _UUID_PATTERN,
        _run_async_in_thread,
        _service_error_payload,
    )

    if not user_id or not _UUID_PATTERN.match(str(user_id)):
        return {"success": False, "error": "invalid_user_id"}
    if not order_id or not _UUID_PATTERN.match(str(order_id)):
        return {"success": False, "error": "invalid_order_id"}

    date_str = (proposed_delivery_date or "").strip()
    if not date_str:
        return {"success": False, "error": "proposed_delivery_date required (YYYY-MM-DD)"}
    try:
        proposed_date = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
    except ValueError:
        return {
            "success": False,
            "error": "proposed_delivery_date must be ISO date (YYYY-MM-DD)",
        }

    # KST 기준 오늘 이상 (router 와 동일 정책 — 과거 날짜 차단)
    _kst_now = datetime.now(timezone(timedelta(hours=9)))
    today_kst = _kst_now.date()
    if proposed_date < today_kst:
        return {
            "success": False,
            "error": "proposed_delivery_date must be today or later (KST)",
            "code": 422,
        }

    from app.services.order_service import order_service

    payload: dict = {"proposed_delivery_date": proposed_date.isoformat()}
    if notes:
        payload["notes"] = notes
    user_dict = {"id": str(user_id)}

    try:
        change = _run_async_in_thread(
            lambda: order_service.submit_delivery_date_change(
                order_id=order_id, payload=payload, user=user_dict
            )
        )
        return {"success": True, "change": change}
    except Exception as e:
        return _service_error_payload(e)


@tool(
    name="accept_delivery_date_change",
    description=(
        "상대방이 제시한 PENDING 납품일 변경 카드를 수락한다. "
        "사용자가 채팅방의 납품일 변경 카드를 보고 '수락해줘', 'OK', '좋아요', "
        "'그 날짜로 진행', '날짜 변경 동의' 같은 자연어로 지시하면 호출하라. "
        "수락 즉시: (1) orders.delivery_date 가 새 날짜로 갱신, "
        "(2) 양 당사자 캘린더가 새 납품일로 자동 이동(옛 일정 row 는 soft-delete), "
        "(3) 채팅방 PENDING 카드 상태가 ACCEPTED 로 자동 동기화되어 수락/거절 버튼이 사라진다. "
        "본인이 제시한 변경 요청은 수락 불가 (상대방만)."
    ),
    parameters={
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
    groups=("inventory_order",),
)
def accept_delivery_date_change(
    user_id: str = "",
    order_id: str = "",
    change_id: str = "",
) -> dict:
    """상대방의 PENDING 납품일 변경 요청을 수락. orders.delivery_date 갱신 + 캘린더 재동기화.

    LLM 자연어 트리거 예: "수락해줘", "OK", "그 날짜로 좋아요", "납품일 변경 동의".
    채팅 DELIVERY_DATE_ACCEPTED 카드 발송 + PENDING 카드 status → ACCEPTED 자동 동기화.
    양 당사자 캘린더가 새 납품일로 자동 이동(옛 event_date row 는 soft-delete).
    본인 제시 변경 요청은 수락 불가 (상대방만).

    반환:
      성공: {success: True, change: {...accepted delivery_date_change row...}}
      실패: {success: False, error: ..., code: <http_status>}
    """
    from app.services.agent_tools import (
        _UUID_PATTERN,
        _run_async_in_thread,
        _service_error_payload,
    )

    if not user_id or not _UUID_PATTERN.match(str(user_id)):
        return {"success": False, "error": "invalid_user_id"}
    if not order_id or not _UUID_PATTERN.match(str(order_id)):
        return {"success": False, "error": "invalid_order_id"}
    if not change_id or not _UUID_PATTERN.match(str(change_id)):
        return {"success": False, "error": "invalid_change_id"}

    from app.services.order_service import order_service
    user_dict = {"id": str(user_id)}

    try:
        change = _run_async_in_thread(
            lambda: order_service.accept_delivery_date_change(
                order_id=order_id, change_id=change_id, user=user_dict
            )
        )
        return {"success": True, "change": change}
    except Exception as e:
        return _service_error_payload(e)


@tool(
    name="reject_delivery_date_change",
    description=(
        "상대방이 제시한 PENDING 납품일 변경 카드를 거절한다. "
        "사용자가 '거절해줘', '안 돼', '그 날짜는 어려워요', '날짜 변경 거부' 같은 "
        "자연어로 지시하면 호출하라. 거절 즉시 채팅방 PENDING 카드 상태가 REJECTED 로 "
        "자동 동기화되어 수락/거절 버튼이 사라지고 거절 시스템 메시지가 발송된다. "
        "본인이 제시한 변경 요청은 거절 불가 (상대방만)."
    ),
    parameters={
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
    groups=("inventory_order",),
)
def reject_delivery_date_change(
    user_id: str = "",
    order_id: str = "",
    change_id: str = "",
) -> dict:
    """상대방의 PENDING 납품일 변경 요청을 거절. 채팅 DELIVERY_DATE_REJECTED 카드 발송.

    LLM 자연어 트리거 예: "거절해줘", "안 돼", "그 날짜는 어려워요", "납품일 변경 거부".
    채팅방의 PENDING 카드 status 도 REJECTED 로 자동 동기화. 본인 제시 변경 요청은 거절 불가.

    반환:
      성공: {success: True, change: {...rejected delivery_date_change row...}}
      실패: {success: False, error: ..., code: <http_status>}
    """
    from app.services.agent_tools import (
        _UUID_PATTERN,
        _run_async_in_thread,
        _service_error_payload,
    )

    if not user_id or not _UUID_PATTERN.match(str(user_id)):
        return {"success": False, "error": "invalid_user_id"}
    if not order_id or not _UUID_PATTERN.match(str(order_id)):
        return {"success": False, "error": "invalid_order_id"}
    if not change_id or not _UUID_PATTERN.match(str(change_id)):
        return {"success": False, "error": "invalid_change_id"}

    from app.services.order_service import order_service
    user_dict = {"id": str(user_id)}

    try:
        change = _run_async_in_thread(
            lambda: order_service.reject_delivery_date_change(
                order_id=order_id, change_id=change_id, user=user_dict
            )
        )
        return {"success": True, "change": change}
    except Exception as e:
        return _service_error_payload(e)
