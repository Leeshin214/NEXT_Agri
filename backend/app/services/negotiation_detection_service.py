"""
negotiation_detection_service — 채팅 협상 의도 감지 (US-2, 2026-05-04)

POST /chat/rooms/{room_id}/messages 직후 BackgroundTasks 로 비동기 호출되어
사용자 평문 메시지에서 가격 협상 의도(품목·수량·단위·단가) 를 감지한다.

핵심 보안 원칙:
- 자동 등록 절대 X — 감지 결과는 metadata.draft_negotiation 으로만 저장
- 발신자 본인에게만 WS 카드 노출 (send_private_message)
- 등록은 별도로 사용자가 [등록] 버튼 클릭 시 기존 propose_counter_offer 흐름 사용
- confidence < 0.7 이면 metadata 저장도 안 함 (false-positive 차단)

흐름:
  send_message 응답 후 BackgroundTasks
    -> process_message_for_negotiation(message_id, room_id, sender_id, content)
        -> _build_room_context (chat_rooms + 연결된 order_items + products)
        -> detect_negotiation_intent (OpenAI structured output)
        -> confidence >= 0.7 이면 metadata UPDATE + WS 푸시 (sender 본인)

WS 이벤트:
  type: "negotiation_draft_detected"
  payload: { message_id, room_id, draft: { product_name, quantity, unit, unit_price,
                                            confidence, detected_at } }
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from app.core.llm import get_openai_client, DEFAULT_MODEL
from app.core.supabase import get_supabase_client
from app.websocket.connection_manager import manager as ws_manager


logger = logging.getLogger(__name__)


# 감지 신뢰도 컷오프 — 이 값 미만이면 metadata 저장도 WS 푸시도 안 함
_CONFIDENCE_THRESHOLD: float = 0.7

# OpenAI 호출 비용 절약 — 짧은 응답 강제
_DETECTION_MODEL = DEFAULT_MODEL  # gpt-4o-mini
_DETECTION_TEMPERATURE = 0.0       # 결정적 출력
_DETECTION_MAX_TOKENS = 200

# 빈 / 너무 짧은 메시지는 LLM 호출조차 하지 않음
_MIN_CONTENT_LENGTH = 4


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def process_message_for_negotiation(
    *,
    message_id: UUID | str,
    room_id: UUID | str,
    sender_id: UUID | str,
    content: str,
) -> None:
    """메시지 발송 직후 BackgroundTasks 가 호출하는 진입점.

    실패는 모두 로그로 흡수 — 채팅 흐름을 막지 않는다.
    """
    message_id_str = str(message_id)
    room_id_str = str(room_id)
    sender_id_str = str(sender_id)

    try:
        if not content or len(content.strip()) < _MIN_CONTENT_LENGTH:
            return

        # 1) 채팅방 컨텍스트 (협상 가능 여부 + 연관 상품 후보)
        ctx = await _build_room_context(room_id_str, sender_id_str)
        if ctx is None:
            return

        # 2) OpenAI 감지 호출
        draft = await detect_negotiation_intent(
            message_text=content,
            room_context=ctx,
        )
        if draft is None:
            return

        confidence = float(draft.get("confidence") or 0.0)
        if confidence < _CONFIDENCE_THRESHOLD:
            return

        # 3) metadata.draft_negotiation 저장 + WS 푸시
        detected_at = datetime.now(timezone.utc).isoformat()
        draft_payload = {
            "product_name": draft.get("product_name"),
            "quantity": draft.get("quantity"),
            "unit": draft.get("unit"),
            "unit_price": draft.get("unit_price"),
            "confidence": round(confidence, 3),
            "detected_at": detected_at,
            "dismissed_at": None,
        }

        await _save_draft_to_message_metadata(message_id_str, draft_payload)

        # WS 푸시 — 발신자 본인에게만
        ws_payload = {
            "type": "negotiation_draft_detected",
            "message_id": message_id_str,
            "room_id": room_id_str,
            "target_user_id": sender_id_str,  # 클라이언트 측 추가 가드
            "draft": draft_payload,
        }
        try:
            await ws_manager.send_private_message(sender_id_str, ws_payload)
        except Exception as e:
            logger.error(
                "[negotiation_detection] WS push 실패 (무시): user=%s err=%s: %s",
                sender_id_str,
                type(e).__name__,
                e,
            )

    except Exception as e:
        # 모든 예외는 흡수 — 메시지 발송 흐름은 이미 응답 완료 상태이므로
        logger.error(
            "[negotiation_detection.process_message_for_negotiation] 예외 (무시): "
            "message_id=%s room_id=%s err=%s: %s",
            message_id_str,
            room_id_str,
            type(e).__name__,
            e,
        )


async def detect_negotiation_intent(
    *,
    message_text: str,
    room_context: dict,
) -> Optional[dict]:
    """OpenAI structured output 으로 협상 의도 감지.

    반환:
        성공 시 dict {product_name, quantity, unit, unit_price, confidence}
        confidence 0.0~1.0 float
        실패/감지 안 됨 시 None
    """
    text = (message_text or "").strip()
    if not text:
        return None

    system_prompt = _build_system_prompt(room_context)
    user_prompt = (
        "다음 채팅 메시지에서 가격 협상 의도(품목·수량·단가)를 감지해 JSON 으로 반환하세요.\n"
        f"메시지: {text}"
    )

    try:
        client = get_openai_client()
        response = await client.chat.completions.create(
            model=_DETECTION_MODEL,
            temperature=_DETECTION_TEMPERATURE,
            max_tokens=_DETECTION_MAX_TOKENS,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
    except Exception as e:
        logger.warning(
            "[negotiation_detection.detect_negotiation_intent] OpenAI 호출 실패: %s: %s",
            type(e).__name__,
            e,
        )
        return None

    raw = (response.choices[0].message.content or "").strip()
    if not raw:
        return None

    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError) as e:
        logger.warning(
            "[negotiation_detection] JSON parse 실패 raw=%s err=%s",
            raw[:200],
            e,
        )
        return None

    return _normalize_detection_result(parsed)


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------


_SYSTEM_PROMPT_BASE = """당신은 한국어 B2B 농산물 거래 채팅에서 '가격 협상 의도'를 추출하는 분석기입니다.

[감지 대상]
- 사용자가 특정 품목·수량·단가(또는 총액)를 언급하며 거래 협상을 시도하는 메시지.
- 예시(높은 신뢰): "옥수수 50kg 7만원에 어때요?", "사과 10박스 박스당 4만원 가능할까요?"
- 예시(중간 신뢰): "양파 박스에 2만원이면 가능?" (수량 누락)
- 예시(낮은 신뢰/0): "안녕하세요", "오늘 날씨 좋네요", "확인하셨나요?"

[출력 규약]
다음 JSON 스키마로만 응답합니다. 마크다운/설명 금지.
{
  "product_name": string|null,    // 품목명 (한국어). 모르면 null.
  "quantity": integer|null,       // 정수. 모르면 null.
  "unit": string|null,            // "kg" | "box" | "piece" | "bag" | "개" | "포대" 등 한국어/영어 단위. 모르면 null.
  "unit_price": integer|null,     // 1단위당 단가(원, KRW 정수). "7만원에 50kg" 처럼 총액만 있으면 quantity 로 나누어 계산.
  "confidence": number            // 0.0 ~ 1.0. 품목+수량+단가가 모두 명시되면 0.85 이상, 일부만 있으면 0.5~0.7, 안부/잡담은 0.0~0.2.
}

[원칙]
1. 단순 안부/잡담/확인 질문은 confidence 0.2 이하.
2. 품목·수량·단가 셋 중 두 가지만 명시되어도 추출은 하되 confidence 는 0.6 이하.
3. 셋 다 명확하면 confidence 0.8~0.95.
4. 통화는 KRW 정수만 (콤마/원 단위 제거).
5. 상품 이름은 한국어 명사 그대로 (예: "옥수수", "사과", "양파").
6. unit_price 가 명시 단가가 아니라 총액이면 quantity 로 나눈 정수를 반환. 0 이하/소수점 결과는 null.
7. 메시지에 협상 의도가 전혀 없으면 confidence 0 + 모든 필드 null.
"""


def _build_system_prompt(room_context: dict) -> str:
    """방 컨텍스트를 시스템 프롬프트 끝에 부착해 LLM 추론 가이드."""
    lines = [_SYSTEM_PROMPT_BASE]

    candidates = room_context.get("candidate_products") or []
    if candidates:
        lines.append("\n[참고: 이 채팅방에서 거래된 적 있는 상품 후보]")
        for c in candidates[:8]:
            name = c.get("name") or "-"
            unit = c.get("unit") or ""
            lines.append(f"- {name}{f' ({unit})' if unit else ''}")
        lines.append("")

    role_label = "판매자" if room_context.get("sender_role") == "SELLER" else "구매자"
    lines.append(f"[발신자 역할] {role_label}")
    return "\n".join(lines)


def _normalize_detection_result(parsed: Any) -> Optional[dict]:
    """LLM JSON 응답을 안전하게 정규화."""
    if not isinstance(parsed, dict):
        return None

    def _coerce_int(v: Any) -> Optional[int]:
        if v is None:
            return None
        if isinstance(v, bool):
            return None
        if isinstance(v, int):
            return v
        try:
            return int(str(v).strip().replace(",", ""))
        except (ValueError, TypeError, AttributeError):
            return None

    def _coerce_float(v: Any) -> float:
        if v is None:
            return 0.0
        if isinstance(v, bool):
            return 0.0
        try:
            f = float(v)
        except (ValueError, TypeError):
            return 0.0
        if f < 0:
            return 0.0
        if f > 1:
            return 1.0
        return f

    def _coerce_str(v: Any) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip()
        if not s or s.lower() in ("null", "none", "-"):
            return None
        return s

    product_name = _coerce_str(parsed.get("product_name"))
    quantity = _coerce_int(parsed.get("quantity"))
    unit = _coerce_str(parsed.get("unit"))
    unit_price = _coerce_int(parsed.get("unit_price"))
    confidence = _coerce_float(parsed.get("confidence"))

    # 품목명도 없고 단가도 없으면 의미 없는 감지 — None 으로 판단해 호출 측에서 skip 가능
    if not product_name and unit_price is None and quantity is None:
        return None

    # 음수/비정상 정수 차단
    if quantity is not None and quantity <= 0:
        quantity = None
    if unit_price is not None and unit_price <= 0:
        unit_price = None

    return {
        "product_name": product_name,
        "quantity": quantity,
        "unit": unit,
        "unit_price": unit_price,
        "confidence": confidence,
    }


async def _build_room_context(room_id: str, sender_id: str) -> Optional[dict]:
    """채팅방 + (있으면) 연결 주문의 상품 후보를 모아 LLM 컨텍스트 dict 생성.

    실패 시 None 반환 — 호출 측에서 감지를 스킵.
    """
    supabase = get_supabase_client()

    try:
        room_result = await asyncio.to_thread(
            lambda: supabase.table("chat_rooms")
            .select("id, order_id, seller_id, buyer_id")
            .eq("id", room_id)
            .limit(1)
            .execute()
        )
        room = (room_result.data or [None])[0]
        if not room:
            return None
    except Exception as e:
        logger.warning("[negotiation_detection._build_room_context] room 조회 실패: %s", e)
        return None

    seller_id = str(room.get("seller_id") or "")
    buyer_id = str(room.get("buyer_id") or "")
    if sender_id == seller_id:
        sender_role = "SELLER"
    elif sender_id == buyer_id:
        sender_role = "BUYER"
    else:
        sender_role = "UNKNOWN"

    candidate_products: list[dict] = []
    order_id = room.get("order_id")
    if order_id:
        try:
            items_result = await asyncio.to_thread(
                lambda: supabase.table("order_items")
                .select("product_id, products(name, unit)")
                .eq("order_id", str(order_id))
                .execute()
            )
            seen: set[str] = set()
            for it in items_result.data or []:
                product = it.get("products") or {}
                if not isinstance(product, dict):
                    continue
                name = product.get("name")
                if not name or name in seen:
                    continue
                seen.add(name)
                candidate_products.append(
                    {"name": name, "unit": product.get("unit")}
                )
        except Exception as e:
            logger.warning(
                "[negotiation_detection._build_room_context] order_items 조회 실패 (무시): %s",
                e,
            )

    return {
        "room_id": room_id,
        "order_id": order_id,
        "seller_id": seller_id,
        "buyer_id": buyer_id,
        "sender_role": sender_role,
        "candidate_products": candidate_products,
    }


async def _save_draft_to_message_metadata(
    message_id: str, draft_payload: dict
) -> None:
    """messages.metadata['draft_negotiation'] = draft_payload UPDATE.

    JSONB 컬럼 부분 업데이트 — 기존 metadata 가 있으면 머지, 없으면 새로 생성.
    SECURITY DEFINER RPC 가 없으므로 fetch -> mutate -> update 패턴 사용 (단건 mutation).
    """
    supabase = get_supabase_client()
    try:
        existing = await asyncio.to_thread(
            lambda: supabase.table("messages")
            .select("id, metadata")
            .eq("id", message_id)
            .limit(1)
            .execute()
        )
        row = (existing.data or [None])[0]
        if not row:
            logger.warning(
                "[negotiation_detection._save_draft] message not found id=%s",
                message_id,
            )
            return

        merged_metadata = dict(row.get("metadata") or {})
        merged_metadata["draft_negotiation"] = draft_payload

        await asyncio.to_thread(
            lambda: supabase.table("messages")
            .update({"metadata": merged_metadata})
            .eq("id", message_id)
            .execute()
        )
    except Exception as e:
        logger.error(
            "[negotiation_detection._save_draft] UPDATE 실패 message_id=%s err=%s: %s",
            message_id,
            type(e).__name__,
            e,
        )


# ---------------------------------------------------------------------------
# Dismiss — 사용자가 [무시] 클릭 시 호출
# ---------------------------------------------------------------------------


async def dismiss_draft_negotiation(
    *,
    message_id: UUID | str,
    user_id: UUID | str,
) -> dict:
    """metadata.draft_negotiation.dismissed_at = NOW() 채움.

    가드:
    - 메시지가 본인이 보낸 것이 아니면 403 (router 에서 raise)
    - draft_negotiation 자체가 없으면 404
    - 이미 dismissed_at 이 있어도 멱등 — 그대로 통과
    반환: 갱신된 draft_negotiation dict
    """
    from fastapi import HTTPException, status

    supabase = get_supabase_client()
    message_id_str = str(message_id)
    user_id_str = str(user_id)

    existing = await asyncio.to_thread(
        lambda: supabase.table("messages")
        .select("id, sender_id, metadata")
        .eq("id", message_id_str)
        .limit(1)
        .execute()
    )
    row = (existing.data or [None])[0]
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="메시지를 찾을 수 없습니다.",
        )

    if str(row.get("sender_id")) != user_id_str:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="본인이 보낸 메시지에 대해서만 협상 초안을 무시할 수 있습니다.",
        )

    metadata = dict(row.get("metadata") or {})
    draft = metadata.get("draft_negotiation")
    if not isinstance(draft, dict):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="이 메시지에 협상 초안이 없습니다.",
        )

    # 멱등: 이미 dismissed_at 이 있으면 그대로 반환
    if draft.get("dismissed_at"):
        return draft

    draft["dismissed_at"] = datetime.now(timezone.utc).isoformat()
    metadata["draft_negotiation"] = draft

    await asyncio.to_thread(
        lambda: supabase.table("messages")
        .update({"metadata": metadata})
        .eq("id", message_id_str)
        .execute()
    )

    return draft
