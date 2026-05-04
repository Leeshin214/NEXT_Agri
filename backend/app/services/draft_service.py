"""
draft_service — 채팅 답장 초안 생성 (US-1, 2026-05-03)

POST /api/v1/chat/draft 가 호출하는 단일 함수 generate_chat_draft 만 노출.

핵심 정책:
- 메시지 DB 저장 안 함 — 초안 텍스트만 반환
- chat_node / send_chat_message 도구 미사용 — 단순 OpenAI 호출 + 컨텍스트 텍스트
- 채팅방 권한 검증 (caller 가 seller/buyer 여야 함)
- 컨텍스트: chat_room.order_id 의 주문 상세, 최근 20개 메시지,
  상대방 사용자 정보 (이름/회사명/역할)
- 응답 톤은 chat_node 와 일관 — 마크다운 별표·리스트 기호 금지, plain text 본문만
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException, status

from app.core.llm import get_openai_client
from app.core.supabase import get_supabase_client


logger = logging.getLogger(__name__)


_RECENT_MESSAGE_LIMIT = 20
_DRAFT_MODEL = "gpt-4o-mini"
_DRAFT_TEMPERATURE = 0.5
_DRAFT_MAX_TOKENS = 400


# ---------------------------------------------------------------------------
# 컨텍스트 빌더
# ---------------------------------------------------------------------------


async def _fetch_chat_room(room_id: UUID) -> Optional[dict]:
    """chat_rooms 단건 조회. chat_rooms 에는 deleted_at 컬럼이 없다 (SKILL_DB.md 검증)."""
    supabase = get_supabase_client()
    result = await asyncio.to_thread(
        lambda: supabase.table("chat_rooms")
        .select("id, order_id, seller_id, buyer_id, created_at")
        .eq("id", str(room_id))
        .limit(1)
        .execute()
    )
    return (result.data or [None])[0]


async def _fetch_user(user_id: str) -> dict:
    """users 단건 조회 (이름/회사명/역할). 실패 시 빈 dict."""
    supabase = get_supabase_client()
    try:
        result = await asyncio.to_thread(
            lambda: supabase.table("users")
            .select("id, name, company_name, role")
            .eq("id", user_id)
            .is_("deleted_at", None)
            .limit(1)
            .execute()
        )
        return (result.data or [{}])[0] or {}
    except Exception as e:
        logger.warning("[draft_service] _fetch_user failed user_id=%s err=%s", user_id, e)
        return {}


async def _fetch_recent_messages(room_id: UUID, limit: int = _RECENT_MESSAGE_LIMIT) -> list[dict]:
    """최근 N개 메시지 시간순(과거→현재) 정렬.

    DB 는 created_at DESC + LIMIT 으로 가져온 뒤 메모리에서 reverse.
    soft-deleted 메시지(.is_('deleted_at', None)) 는 제외.
    """
    supabase = get_supabase_client()
    try:
        result = await asyncio.to_thread(
            lambda: supabase.table("messages")
            .select(
                "id, sender_id, content, message_type, metadata, created_at, "
                "sender:users!sender_id(name, company_name, role)"
            )
            .eq("room_id", str(room_id))
            .is_("deleted_at", None)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return list(reversed(result.data or []))
    except Exception as e:
        logger.warning("[draft_service] _fetch_recent_messages failed room_id=%s err=%s", room_id, e)
        return []


async def _fetch_order_summary(order_id: str) -> Optional[dict]:
    """주문 + order_items + products 임베딩으로 한 번에 조회.

    응답: {order_number, status, total_amount, delivery_date, items: [{product_name, quantity, unit, unit_price}]}
    실패 시 None.
    """
    supabase = get_supabase_client()
    try:
        order_result = await asyncio.to_thread(
            lambda: supabase.table("orders")
            .select(
                "id, order_number, status, total_amount, delivery_date, "
                "delivery_address, notes, "
                "order_items(quantity, unit_price, products(name, unit))"
            )
            .eq("id", order_id)
            .is_("deleted_at", None)
            .limit(1)
            .execute()
        )
        order = (order_result.data or [None])[0]
        if not order:
            return None

        items_raw = order.pop("order_items", None) or []
        items: list[dict] = []
        for it in items_raw:
            product = (it.pop("products", None) or {}) if isinstance(it, dict) else {}
            items.append(
                {
                    "product_name": product.get("name"),
                    "unit": product.get("unit"),
                    "quantity": it.get("quantity") if isinstance(it, dict) else None,
                    "unit_price": it.get("unit_price") if isinstance(it, dict) else None,
                }
            )
        order["items"] = items
        return order
    except Exception as e:
        logger.warning("[draft_service] _fetch_order_summary failed order_id=%s err=%s", order_id, e)
        return None


# ---------------------------------------------------------------------------
# 시스템 프롬프트 빌더
# ---------------------------------------------------------------------------


def _format_message_for_prompt(msg: dict, my_user_id: str) -> str:
    """단일 메시지를 한 줄 텍스트로 변환. 발신자/수신자 구분."""
    sender_id = str(msg.get("sender_id") or "")
    sender_obj = msg.get("sender") or {}
    sender_name = sender_obj.get("name") or sender_obj.get("company_name") or "상대방"
    speaker = "나" if sender_id == my_user_id else sender_name

    content = (msg.get("content") or "").replace("\n", " ").strip()
    if not content:
        return ""

    # SYSTEM/협상 등 이벤트 메시지는 라벨로 표시
    msg_type = (msg.get("message_type") or "TEXT").upper()
    if msg_type == "SYSTEM":
        return f"[시스템] {content}"
    if msg_type == "COUNTER_OFFER":
        meta = msg.get("metadata") or {}
        amount = meta.get("proposed_total_amount")
        return f"[{speaker}] (협상가 제시 {amount}원) {content}" if amount else f"[{speaker}] {content}"
    if msg_type in ("OFFER_ACCEPTED", "OFFER_REJECTED"):
        return f"[시스템] {content}"
    if msg_type in ("ORDER_STATUS", "ORDER_CANCELLED"):
        return f"[시스템] {content}"
    if msg_type in ("DELIVERY_DATE_CHANGE", "DELIVERY_DATE_ACCEPTED", "DELIVERY_DATE_REJECTED"):
        return f"[시스템] {content}"
    return f"[{speaker}] {content}"


def _format_order_for_prompt(order: dict) -> str:
    """주문 요약을 시스템 프롬프트용 텍스트로 변환."""
    order_number = order.get("order_number") or "-"
    status_str = order.get("status") or "-"
    total = order.get("total_amount")
    delivery_date = order.get("delivery_date") or "-"
    address = order.get("delivery_address") or "-"

    items = order.get("items") or []
    item_lines: list[str] = []
    for it in items:
        name = it.get("product_name") or "-"
        qty = it.get("quantity")
        unit = it.get("unit") or ""
        price = it.get("unit_price")
        if qty is not None and price is not None:
            item_lines.append(f"{name} {qty}{unit} (단가 {price}원)")
        elif qty is not None:
            item_lines.append(f"{name} {qty}{unit}")
        else:
            item_lines.append(name)
    items_text = ", ".join(item_lines) if item_lines else "-"

    total_text = f"{total}원" if isinstance(total, int) else "-"
    return (
        f"주문번호 {order_number} / 상태 {status_str} / 총액 {total_text} / "
        f"납품일 {delivery_date} / 배송지 {address}\n"
        f"품목: {items_text}"
    )


def _resolve_my_role(room: dict, my_user_id: str) -> str:
    """채팅방 안에서 caller 가 SELLER 인지 BUYER 인지 결정."""
    if str(room.get("seller_id")) == my_user_id:
        return "SELLER"
    if str(room.get("buyer_id")) == my_user_id:
        return "BUYER"
    return "UNKNOWN"


def _build_system_prompt(
    *,
    me: dict,
    counterpart: dict,
    my_role: str,
    order_summary: Optional[dict],
    messages_text: str,
) -> str:
    me_name = me.get("name") or me.get("company_name") or "본인"
    me_company = me.get("company_name") or "-"
    cp_name = counterpart.get("name") or counterpart.get("company_name") or "상대방"
    cp_company = counterpart.get("company_name") or "-"
    cp_role = counterpart.get("role") or ("BUYER" if my_role == "SELLER" else "SELLER")

    role_label_me = "판매자" if my_role == "SELLER" else "구매자" if my_role == "BUYER" else "사용자"
    role_label_cp = "구매자" if cp_role == "BUYER" else "판매자" if cp_role == "SELLER" else "상대방"

    order_block = (
        f"[연결된 주문 정보]\n{_format_order_for_prompt(order_summary)}\n"
        if order_summary
        else "[연결된 주문 정보]\n없음 (일반 대화방)\n"
    )

    msgs_block = (
        f"[최근 대화 (오래된 순)]\n{messages_text}\n"
        if messages_text.strip()
        else "[최근 대화 (오래된 순)]\n(이전 대화 없음)\n"
    )

    return (
        "당신은 fresh link 농산물 B2B 플랫폼의 채팅 답장 보조 AI입니다.\n"
        "사용자가 채팅방에서 상대방에게 보낼 답장 본문 초안을 한국어로 작성합니다.\n"
        "\n"
        "[절대 금지]\n"
        "1. 마크다운 별표(**), 리스트 기호(-, *, 1.) 사용 금지.\n"
        "2. 본문 외 메타 설명(예: '아래는 초안입니다', '다음과 같이 답장하시면 됩니다') 금지.\n"
        "3. 인사 외 불필요한 수식어 남발 금지.\n"
        "\n"
        "[작성 규칙]\n"
        "- 응답은 사용자가 그대로 복사해 보낼 답장 본문만 출력합니다.\n"
        "- 톤은 정중하지만 간결한 비즈니스 한국어. 상대 호칭은 자연스럽게(님 등).\n"
        "- 사용자의 지시가 가격/수량/납기일 등 구체 수치를 요구하면 위 주문/대화 컨텍스트에서 가져와 정확히 반영합니다.\n"
        "- 컨텍스트에 없어 추정해야 하면 추정한 부분을 명시하지 말고, 자연스러운 표현으로 처리합니다.\n"
        "- 상대 메시지에 대한 답이 필요한 흐름이면 직전 메시지 맥락을 이어갑니다.\n"
        "- 길이는 1~3문장이 기본, 필요한 경우만 4~5문장.\n"
        "\n"
        f"[본인 정보]\n이름 {me_name} / 회사 {me_company} / 역할 {role_label_me}\n"
        f"\n[상대방 정보]\n이름 {cp_name} / 회사 {cp_company} / 역할 {role_label_cp}\n"
        f"\n{order_block}"
        f"\n{msgs_block}"
    )


# ---------------------------------------------------------------------------
# 텍스트 후처리
# ---------------------------------------------------------------------------


def _sanitize_draft(text: str) -> str:
    """LLM 출력에서 마크다운/메타 어구 제거."""
    if not text:
        return ""
    cleaned = text.strip()
    # 마크다운 강조 제거
    cleaned = cleaned.replace("**", "").replace("*", "")
    # 코드블록 펜스 제거
    if cleaned.startswith("```"):
        # ```...\ncontent\n```
        parts = cleaned.split("```")
        # ['', 'maybe lang\ncontent\n', ''] 형태일 가능성
        for p in parts:
            p_stripped = p.strip()
            if p_stripped:
                # 첫 줄이 언어 라벨 (e.g. 'text', 'plain') 이면 제거
                lines = p_stripped.split("\n", 1)
                if len(lines) == 2 and len(lines[0].strip()) <= 12 and " " not in lines[0].strip():
                    cleaned = lines[1].strip()
                else:
                    cleaned = p_stripped
                break

    # 흔한 메타 prefix 제거 — 첫 줄에 "초안:", "답장:", "예시:" 등이 있으면 제거
    META_PREFIXES = ("초안:", "답장:", "예시:", "답변:", "draft:", "Draft:")
    for p in META_PREFIXES:
        if cleaned.startswith(p):
            cleaned = cleaned[len(p):].strip()
            break

    return cleaned


# ---------------------------------------------------------------------------
# 메인 함수
# ---------------------------------------------------------------------------


async def generate_chat_draft(
    *,
    user_id: UUID | str,
    room_id: UUID,
    instruction: str,
) -> str:
    """채팅방 컨텍스트 기반 답장 초안 텍스트 생성.

    - 채팅방 참여자(seller/buyer) 가 아니면 403
    - 채팅방 미존재 시 404
    - OpenAI 호출 실패 시 502
    - 초안은 메시지 테이블에 저장하지 않음
    """
    user_id_str = str(user_id)
    instruction_clean = (instruction or "").strip()
    if not instruction_clean:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="instruction(지시문)이 비어 있습니다.",
        )

    # 1) 채팅방 조회 + 권한 검증
    room = await _fetch_chat_room(room_id)
    if not room:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="채팅방을 찾을 수 없습니다.",
        )

    seller_id = str(room.get("seller_id") or "")
    buyer_id = str(room.get("buyer_id") or "")
    if user_id_str not in (seller_id, buyer_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="이 채팅방에 접근할 권한이 없습니다.",
        )

    my_role = _resolve_my_role(room, user_id_str)
    counterpart_id = buyer_id if my_role == "SELLER" else seller_id

    # 2) 컨텍스트 병렬 조회 (me, counterpart, messages, order)
    order_id = room.get("order_id")
    me_task = _fetch_user(user_id_str)
    cp_task = _fetch_user(counterpart_id)
    msgs_task = _fetch_recent_messages(room_id, _RECENT_MESSAGE_LIMIT)
    order_task: asyncio.Future = (
        asyncio.ensure_future(_fetch_order_summary(str(order_id)))
        if order_id
        else asyncio.ensure_future(asyncio.sleep(0, result=None))  # 즉시 None 반환
    )

    me, counterpart, recent_messages, order_summary = await asyncio.gather(
        me_task, cp_task, msgs_task, order_task
    )

    # 3) 시스템 프롬프트 작성
    msg_lines = [_format_message_for_prompt(m, user_id_str) for m in recent_messages]
    msg_lines = [line for line in msg_lines if line]
    messages_text = "\n".join(msg_lines)

    system_prompt = _build_system_prompt(
        me=me or {},
        counterpart=counterpart or {},
        my_role=my_role,
        order_summary=order_summary,
        messages_text=messages_text,
    )

    user_prompt = (
        "사용자가 보낼 답장 초안을 작성해 주세요.\n"
        f"[사용자 지시]\n{instruction_clean}\n"
        "\n"
        "응답은 사용자가 그대로 보낼 답장 본문만 출력하세요. "
        "메타 설명·머리말·꼬리말 모두 금지."
    )

    # 4) OpenAI 호출
    try:
        client = get_openai_client()
        response = await client.chat.completions.create(
            model=_DRAFT_MODEL,
            temperature=_DRAFT_TEMPERATURE,
            max_tokens=_DRAFT_MAX_TOKENS,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
    except Exception as e:
        logger.error("[draft_service] OpenAI call failed room_id=%s err=%s", room_id, e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI 답장 초안 생성에 실패했습니다: {type(e).__name__}",
        ) from e

    raw_text = (response.choices[0].message.content or "").strip()
    draft = _sanitize_draft(raw_text)

    if not draft:
        # LLM 이 빈 텍스트만 반환한 경우 — 사용자가 retry 할 수 있도록 명시 에러
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI가 빈 답장을 반환했습니다. 지시문을 더 구체적으로 작성해 주세요.",
        )

    return draft
