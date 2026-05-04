"""정기배송(Subscription) 관련 도구.

원본: backend/app/services/agent_tools.py 의 subscription 섹션 (단계 1: 본문 그대로 복사 + @tool 데코레이터 추가).
agent_tools.py 의 함수는 단계 2 에서 shim 으로 변환된다.

도메인 helper:
- _normalize_frequency, _normalize_iso_date, _resolve_subscription_items
  : 정기배송 입력 정규화 (자연어 친화).

Cross-domain 의존:
- _UUID_PATTERN, _run_async_in_thread, _service_error_payload
  : agent_tools.py 의 cross-domain helper (단계 2 에서 _shared.py 로 이동 예정).
- _find_product_by_name : product.py 의 도메인 helper (lazy import).

참고:
- 실제 INSERT/UPDATE 비즈니스 로직은 app/services/subscription_service.py 에 구현되어 있다.
  본 도구들은 LLM tool-use 호환 입력(자연어 친화)을 받아 검증한 뒤 그 서비스를 호출한다.
- sync 도구로 등록하기 위해 _run_async_in_thread 로 비동기 서비스 함수를 실행한다
  (이미 검증된 헬퍼; 협상/배송 변경 도구들과 동일 패턴).
"""
from __future__ import annotations

import re
from typing import Optional

from app.core.supabase import get_supabase_client

from .._registry import tool


_SUBSCRIPTION_FREQUENCIES = ("WEEKLY", "BIWEEKLY", "MONTHLY")
_SUBSCRIPTION_FREQ_KO = {
    "매주": "WEEKLY",
    "주간": "WEEKLY",
    "주 1회": "WEEKLY",
    "주1회": "WEEKLY",
    "격주": "BIWEEKLY",
    "2주": "BIWEEKLY",
    "2주마다": "BIWEEKLY",
    "월": "MONTHLY",
    "월간": "MONTHLY",
    "매월": "MONTHLY",
    "한달": "MONTHLY",
    "월1회": "MONTHLY",
    "월 1회": "MONTHLY",
}
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _normalize_frequency(value: Optional[str]) -> Optional[str]:
    """LLM 이 넘긴 frequency 문자열을 표준 코드로 변환. 표준값이 아니면 None."""
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    upper = s.upper()
    if upper in _SUBSCRIPTION_FREQUENCIES:
        return upper
    return _SUBSCRIPTION_FREQ_KO.get(s)


def _normalize_iso_date(value: Optional[str]) -> Optional[str]:
    """YYYY-MM-DD 형태로 정규화. 형식 안 맞으면 None."""
    if not value:
        return None
    s = str(value).strip()[:10]
    if _DATE_PATTERN.match(s):
        return s
    return None


def _resolve_subscription_items(
    supabase,
    *,
    seller_id: str,
    items: list[dict],
) -> tuple[list[dict], list[str]]:
    """LLM 입력 items 를 subscription_service 가 요구하는 dict 리스트로 정규화.

    각 입력 item 은 다음 키를 가질 수 있다:
      - product_id   (UUID, 권장)
      - product_name (UUID 모를 때 사용 — seller_id 범위에서 자동 검색)
      - quantity     (int > 0)
      - unit_price   (int >= 0; 미지정 시 product.price_per_unit 자동 채움)
      - unit         (kg/box/piece 등; 미지정 시 product.unit 자동 채움)

    반환: (정규화된 items 리스트, 에러 메시지 리스트)
      에러가 있으면 호출 측에서 needs_clarification 응답 구성에 사용.
    """
    from app.services.agent_tools import _UUID_PATTERN
    from .product import _find_product_by_name

    resolved: list[dict] = []
    errors: list[str] = []

    if not isinstance(items, list) or not items:
        return resolved, ["items 가 비어 있습니다. 정기배송할 품목/수량/단가를 1개 이상 알려주세요."]

    for idx, raw in enumerate(items):
        if not isinstance(raw, dict):
            errors.append(f"items[{idx}] 형식이 잘못되었습니다 (dict 가 아님).")
            continue

        product_id = (raw.get("product_id") or "").strip()
        product_name = (raw.get("product_name") or "").strip()
        product_row: Optional[dict] = None

        if product_id and _UUID_PATTERN.match(product_id):
            try:
                q = (
                    supabase.table("products")
                    .select("id, name, unit, price_per_unit")
                    .eq("id", product_id)
                    .is_("deleted_at", None)
                )
                if seller_id:
                    q = q.eq("seller_id", seller_id)
                vr = q.execute()
                if not vr.data:
                    errors.append(
                        f"items[{idx}] product_id '{product_id}' 가 판매자 상품에서 확인되지 않습니다."
                    )
                    continue
                product_row = vr.data[0]
            except Exception as e:
                errors.append(f"items[{idx}] 상품 조회 오류: {e}")
                continue
        elif product_name:
            found = _find_product_by_name(supabase, product_name, seller_id)
            if not found:
                errors.append(f"items[{idx}] '{product_name}' 상품을 찾을 수 없습니다.")
                continue
            product_id = found["id"]
            try:
                detail = (
                    supabase.table("products")
                    .select("id, name, unit, price_per_unit")
                    .eq("id", product_id)
                    .is_("deleted_at", None)
                    .execute()
                )
                product_row = detail.data[0] if detail.data else found
            except Exception:
                product_row = found
        else:
            errors.append(f"items[{idx}] product_id 또는 product_name 중 하나는 필요합니다.")
            continue

        try:
            quantity = int(raw.get("quantity"))
        except (TypeError, ValueError):
            errors.append(f"items[{idx}] quantity 가 정수가 아닙니다.")
            continue
        if quantity <= 0:
            errors.append(f"items[{idx}] quantity 는 1 이상이어야 합니다.")
            continue

        unit_price_raw = raw.get("unit_price")
        unit_price: Optional[int] = None
        if unit_price_raw is not None and unit_price_raw != "":
            try:
                unit_price = int(unit_price_raw)
            except (TypeError, ValueError):
                errors.append(f"items[{idx}] unit_price 가 정수가 아닙니다.")
                continue
        if unit_price is None and product_row:
            unit_price = product_row.get("price_per_unit")
        if unit_price is None:
            errors.append(f"items[{idx}] unit_price 가 누락되었습니다.")
            continue
        if unit_price < 0:
            errors.append(f"items[{idx}] unit_price 는 0 이상이어야 합니다.")
            continue

        unit = (raw.get("unit") or "").strip()
        if not unit and product_row:
            unit = product_row.get("unit") or ""
        if not unit:
            errors.append(f"items[{idx}] unit 이 누락되었습니다.")
            continue

        resolved.append({
            "product_id": product_id,
            "quantity": quantity,
            "unit_price": unit_price,
            "unit": unit,
        })

    return resolved, errors


@tool(
    name="create_subscription_request",
    description=(
        "정기배송 요청을 상대방에게 보낸다 (status=PENDING, 상대 수락 시 ACTIVE). "
        "사용자가 '정기배송 요청해줘', '○○를 정기배송으로 받고 싶어', "
        "'매주 ○요일에 ○○ 받기', '○○ 매주 정기배송 등록', '격주로 받고 싶어' 같은 "
        "자연어 요청 시 호출. frequency / start_date / items 가 부족하면 "
        "needs_clarification=true 가 반환되며 절대 등록되지 않으니 사용자에게 다시 물어라. "
        "상대방 user_id 모르면 get_user_profile 로 먼저 조회. "
        "역할은 SELLER↔BUYER 만 허용됨."
    ),
    parameters={
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
    groups=("inventory_order",),
)
def create_subscription_request(
    user_id: str = "",
    target_user_id: str = "",
    frequency: str = "",
    start_date: str = "",
    end_date: Optional[str] = None,
    items: Optional[list[dict]] = None,
    delivery_address: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    """정기배송 요청을 상대방에게 보낸다 (status=PENDING 으로 시작).

    상대방이 accept 하면 ACTIVE, reject 하면 REJECTED 로 전환된다.
    필수 정보(frequency / start_date / items) 가 부족하면
    needs_clarification=True 응답을 돌려 LLM 이 사용자에게 다시 묻도록 한다.

    파라미터:
      user_id: 현재 로그인 사용자 UUID (요청자, created_by 로 저장됨)
      target_user_id: 정기배송 상대방 UUID
      frequency: WEEKLY / BIWEEKLY / MONTHLY (한국어 '매주'/'격주'/'매월' 도 허용)
      start_date: YYYY-MM-DD
      end_date: YYYY-MM-DD (선택)
      items: [{product_id|product_name, quantity, unit_price?, unit?}, ...]
      delivery_address: 납품 주소 (선택)
      notes: 메모 (선택)

    반환:
      성공: {success: True, subscription_id, status: "PENDING", direction, message}
      검증 실패: {success: False, needs_clarification: True, missing: [...], message}
      서비스 실패: {success: False, error, message}
    """
    from app.services.agent_tools import (
        _UUID_PATTERN,
        _run_async_in_thread,
        _service_error_payload,
    )

    user_clean = (user_id or "").strip()
    target_clean = (target_user_id or "").strip()

    if not user_clean or not _UUID_PATTERN.match(user_clean):
        return {"success": False, "error": "invalid_user_id", "message": "현재 사용자 UUID 가 유효하지 않습니다."}
    if not target_clean or not _UUID_PATTERN.match(target_clean):
        return {
            "success": False,
            "needs_clarification": True,
            "missing": ["target_user_id"],
            "message": "정기배송을 누구에게 요청할지 알려주세요. (거래처 이름이나 회사명을 알려주시면 자동으로 찾아드립니다.)",
        }
    if user_clean == target_clean:
        return {
            "success": False,
            "error": "self_subscription_not_allowed",
            "message": "자기 자신에게 정기배송을 요청할 수 없습니다.",
        }

    missing: list[str] = []
    freq_norm = _normalize_frequency(frequency)
    if not freq_norm:
        missing.append("frequency")
    start_norm = _normalize_iso_date(start_date)
    if not start_norm:
        missing.append("start_date")

    end_norm = _normalize_iso_date(end_date) if end_date else None
    if end_date and not end_norm:
        return {
            "success": False,
            "needs_clarification": True,
            "missing": ["end_date"],
            "message": "end_date 는 YYYY-MM-DD 형식이어야 합니다.",
        }

    if missing:
        msg_parts: list[str] = []
        if "frequency" in missing:
            msg_parts.append("배송 주기(매주/격주/매월)")
        if "start_date" in missing:
            msg_parts.append("시작 날짜(YYYY-MM-DD)")
        return {
            "success": False,
            "needs_clarification": True,
            "missing": missing,
            "message": "정기배송을 등록하려면 " + " 와 ".join(msg_parts) + " 가 필요합니다. 알려주세요.",
        }

    # 역할 매칭 — SELLER↔BUYER 만 허용. seller_id, buyer_id 결정.
    try:
        supabase = get_supabase_client()
        me_result = (
            supabase.table("users")
            .select("id, role")
            .eq("id", user_clean)
            .is_("deleted_at", None)
            .limit(1)
            .execute()
        )
        if not me_result.data:
            return {"success": False, "error": "user_not_found", "message": "현재 사용자 정보를 찾을 수 없습니다."}
        my_role = (me_result.data[0].get("role") or "").upper()

        target_result = (
            supabase.table("users")
            .select("id, role, name, company_name")
            .eq("id", target_clean)
            .is_("deleted_at", None)
            .limit(1)
            .execute()
        )
        if not target_result.data:
            return {
                "success": False,
                "error": "target_not_found",
                "message": "정기배송 상대방을 찾을 수 없습니다.",
            }
        target_role = (target_result.data[0].get("role") or "").upper()
        target_label = (
            target_result.data[0].get("company_name")
            or target_result.data[0].get("name")
            or "거래처"
        )
    except Exception as e:
        return {"success": False, "error": str(e)}

    if my_role == "SELLER" and target_role == "BUYER":
        seller_id, buyer_id = user_clean, target_clean
        direction = "SELLER_TO_BUYER"
    elif my_role == "BUYER" and target_role == "SELLER":
        seller_id, buyer_id = target_clean, user_clean
        direction = "BUYER_TO_SELLER"
    else:
        return {
            "success": False,
            "error": "role_mismatch",
            "message": (
                "정기배송은 판매자(SELLER) 와 구매자(BUYER) 간에만 등록할 수 있습니다. "
                f"(나={my_role or '?'}, 상대={target_role or '?'})"
            ),
        }

    resolved_items, item_errors = _resolve_subscription_items(
        supabase, seller_id=seller_id, items=items or []
    )
    if not resolved_items:
        return {
            "success": False,
            "needs_clarification": True,
            "missing": ["items"],
            "message": (
                "정기배송할 품목/수량/단가를 알려주세요.\n"
                + ("\n".join(f"- {e}" for e in item_errors) if item_errors else "예) '망고 2box, 단가 30000원'")
            ),
        }

    from app.services.subscription_service import subscription_service
    from uuid import UUID as _UUID

    payload = {
        "seller_id": seller_id,
        "buyer_id": buyer_id,
        "frequency": freq_norm,
        "start_date": start_norm,
        "end_date": end_norm,
        "delivery_address": delivery_address,
        "notes": notes,
        "items": resolved_items,
    }

    try:
        sub = _run_async_in_thread(
            lambda: subscription_service.create_subscription(
                user_id=_UUID(user_clean), payload=payload
            )
        )
    except Exception as e:
        return _service_error_payload(e)

    return {
        "success": True,
        "subscription_id": sub.get("id") if isinstance(sub, dict) else None,
        "status": sub.get("status") if isinstance(sub, dict) else "PENDING",
        "direction": direction,
        "frequency": freq_norm,
        "start_date": start_norm,
        "end_date": end_norm,
        "items_count": len(resolved_items),
        "target_label": target_label,
        "message": (
            f"{target_label} 에게 정기배송 요청을 보냈습니다 (주기: {freq_norm}, 시작: {start_norm}). "
            "상대방이 수락하면 자동으로 활성화됩니다."
        ),
    }


@tool(
    name="accept_subscription_request",
    description=(
        "받은 정기배송 요청을 수락한다 (PENDING → ACTIVE). "
        "사용자가 받은 정기배송 요청 알림에 '수락해줘', '진행해', 'OK', '좋아요 그렇게 해요' "
        "같이 답할 때 호출. 본인이 만든 요청은 수락 불가 (상대방만 가능). "
        "수락 즉시 양 당사자 캘린더에 다음 배송 일정이 자동 등록됨."
    ),
    parameters={
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
    groups=("inventory_order",),
)
def accept_subscription_request(user_id: str = "", subscription_id: str = "") -> dict:
    """받은 정기배송 요청을 수락한다 (PENDING → ACTIVE).

    - 요청자 본인은 수락 불가 (subscription_service 에서 403).
    - status 가 PENDING 이 아니면 400.
    - ACTIVE 전환 시 양 당사자 캘린더에 다음 배송 일정이 자동 등록된다.
    """
    from app.services.agent_tools import (
        _UUID_PATTERN,
        _run_async_in_thread,
        _service_error_payload,
    )

    user_clean = (user_id or "").strip()
    sub_clean = (subscription_id or "").strip()

    if not user_clean or not _UUID_PATTERN.match(user_clean):
        return {"success": False, "error": "invalid_user_id", "message": "현재 사용자 UUID 가 유효하지 않습니다."}
    if not sub_clean or not _UUID_PATTERN.match(sub_clean):
        return {
            "success": False,
            "needs_clarification": True,
            "missing": ["subscription_id"],
            "message": "수락할 정기배송 ID 를 알려주세요. (정기배송 목록에서 확인)",
        }

    from app.services.subscription_service import subscription_service
    from uuid import UUID as _UUID

    try:
        sub = _run_async_in_thread(
            lambda: subscription_service.accept_subscription(
                subscription_id=_UUID(sub_clean), user_id=_UUID(user_clean)
            )
        )
    except Exception as e:
        return _service_error_payload(e)

    return {
        "success": True,
        "subscription_id": sub.get("id") if isinstance(sub, dict) else sub_clean,
        "status": sub.get("status") if isinstance(sub, dict) else "ACTIVE",
        "next_delivery_date": sub.get("next_delivery_date") if isinstance(sub, dict) else None,
        "message": "정기배송 요청을 수락했습니다. 캘린더에 다음 배송 일정이 자동 등록됩니다.",
    }


@tool(
    name="reject_subscription_request",
    description=(
        "받은 정기배송 요청을 거절한다 (PENDING → REJECTED). "
        "사용자가 '거절해줘', '안 돼', '그 조건은 어려워요', '거절' 같이 답할 때 호출. "
        "본인이 만든 요청은 거절 불가 (상대방만)."
    ),
    parameters={
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
    groups=("inventory_order",),
)
def reject_subscription_request(
    user_id: str = "",
    subscription_id: str = "",
    reason: Optional[str] = None,
) -> dict:
    """받은 정기배송 요청을 거절한다 (PENDING → REJECTED).

    - 요청자 본인은 거절 불가.
    - reason 은 현재 DB 컬럼이 없어 응답 메시지에만 활용된다 (이력 보존은 status=REJECTED 로).
    """
    from app.services.agent_tools import (
        _UUID_PATTERN,
        _run_async_in_thread,
        _service_error_payload,
    )

    user_clean = (user_id or "").strip()
    sub_clean = (subscription_id or "").strip()

    if not user_clean or not _UUID_PATTERN.match(user_clean):
        return {"success": False, "error": "invalid_user_id", "message": "현재 사용자 UUID 가 유효하지 않습니다."}
    if not sub_clean or not _UUID_PATTERN.match(sub_clean):
        return {
            "success": False,
            "needs_clarification": True,
            "missing": ["subscription_id"],
            "message": "거절할 정기배송 ID 를 알려주세요.",
        }

    from app.services.subscription_service import subscription_service
    from uuid import UUID as _UUID

    try:
        _run_async_in_thread(
            lambda: subscription_service.reject_subscription(
                subscription_id=_UUID(sub_clean), user_id=_UUID(user_clean)
            )
        )
    except Exception as e:
        return _service_error_payload(e)

    msg = "정기배송 요청을 거절했습니다."
    if reason:
        msg = f"{msg} (사유: {reason})"
    return {
        "success": True,
        "subscription_id": sub_clean,
        "status": "REJECTED",
        "reason": reason,
        "message": msg,
    }


@tool(
    name="create_subscription_from_order",
    description=(
        "기존 주문의 품목을 그대로 정기배송으로 전환 신청한다 (PENDING). "
        "사용자가 '이 주문을 정기배송으로 전환', '망고 2kg 주문 정기배송으로 바꿔줘', "
        "'방금 그 주문 매주 받게 해줘' 같이 말할 때 호출. "
        "주문의 order_items 가 그대로 subscription_items 로 복제되며 "
        "상대방이 수락하면 자동 활성화된다. 주문 당사자(buyer/seller)만 호출 가능."
    ),
    parameters={
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
    groups=("inventory_order",),
)
def create_subscription_from_order(
    user_id: str = "",
    order_id: str = "",
    frequency: str = "",
    start_date: str = "",
    end_date: Optional[str] = None,
) -> dict:
    """기존 주문의 품목을 그대로 정기배송으로 전환 신청한다.

    예: '망고 2kg 주문을 정기배송으로 전환해줘' → 해당 주문의 order_items 를
        그대로 subscription_items 로 복제하고 PENDING 상태로 등록한다.
    상대방이 수락하면 ACTIVE 로 전환된다.
    """
    from app.services.agent_tools import (
        _UUID_PATTERN,
        _run_async_in_thread,
        _service_error_payload,
    )

    user_clean = (user_id or "").strip()
    order_clean = (order_id or "").strip()

    if not user_clean or not _UUID_PATTERN.match(user_clean):
        return {"success": False, "error": "invalid_user_id", "message": "현재 사용자 UUID 가 유효하지 않습니다."}
    if not order_clean or not _UUID_PATTERN.match(order_clean):
        return {
            "success": False,
            "needs_clarification": True,
            "missing": ["order_id"],
            "message": "어떤 주문을 정기배송으로 전환할지 알려주세요. (주문 번호 또는 주문 ID)",
        }

    missing: list[str] = []
    freq_norm = _normalize_frequency(frequency)
    if not freq_norm:
        missing.append("frequency")
    start_norm = _normalize_iso_date(start_date)
    if not start_norm:
        missing.append("start_date")

    end_norm = _normalize_iso_date(end_date) if end_date else None
    if end_date and not end_norm:
        return {
            "success": False,
            "needs_clarification": True,
            "missing": ["end_date"],
            "message": "end_date 는 YYYY-MM-DD 형식이어야 합니다.",
        }

    if missing:
        msg_parts: list[str] = []
        if "frequency" in missing:
            msg_parts.append("배송 주기(매주/격주/매월)")
        if "start_date" in missing:
            msg_parts.append("시작 날짜(YYYY-MM-DD)")
        return {
            "success": False,
            "needs_clarification": True,
            "missing": missing,
            "message": "정기배송 전환에 " + " 와 ".join(msg_parts) + " 가 필요합니다.",
        }

    try:
        supabase = get_supabase_client()
        order_result = (
            supabase.table("orders")
            .select("id, buyer_id, seller_id, delivery_address, notes, order_number, status")
            .eq("id", order_clean)
            .is_("deleted_at", None)
            .limit(1)
            .execute()
        )
        if not order_result.data:
            return {"success": False, "error": "order_not_found", "message": "해당 주문을 찾을 수 없습니다."}
        order = order_result.data[0]

        if user_clean not in (order.get("buyer_id"), order.get("seller_id")):
            return {
                "success": False,
                "error": "forbidden",
                "message": "해당 주문의 당사자(구매자/판매자)만 정기배송으로 전환할 수 있습니다.",
            }

        items_result = (
            supabase.table("order_items")
            .select("product_id, quantity, unit_price, products(name, unit)")
            .eq("order_id", order_clean)
            .execute()
        )
        raw_items = items_result.data or []
        if not raw_items:
            return {
                "success": False,
                "error": "no_items",
                "message": "해당 주문에 품목이 없어 정기배송으로 전환할 수 없습니다.",
            }

        sub_items: list[dict] = []
        for it in raw_items:
            product = it.get("products") or {}
            unit_value = product.get("unit") if isinstance(product, dict) else None
            try:
                quantity = int(it.get("quantity"))
                unit_price = int(it.get("unit_price"))
            except (TypeError, ValueError):
                continue
            if not it.get("product_id") or quantity <= 0 or unit_price < 0 or not unit_value:
                continue
            sub_items.append({
                "product_id": it["product_id"],
                "quantity": quantity,
                "unit_price": unit_price,
                "unit": unit_value,
            })

        if not sub_items:
            return {
                "success": False,
                "error": "no_valid_items",
                "message": "해당 주문에서 정기배송으로 변환 가능한 유효 품목을 찾지 못했습니다.",
            }

        payload = {
            "seller_id": order["seller_id"],
            "buyer_id": order["buyer_id"],
            "frequency": freq_norm,
            "start_date": start_norm,
            "end_date": end_norm,
            "delivery_address": order.get("delivery_address"),
            "notes": order.get("notes"),
            "items": sub_items,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

    from app.services.subscription_service import subscription_service
    from uuid import UUID as _UUID

    try:
        sub = _run_async_in_thread(
            lambda: subscription_service.create_subscription(
                user_id=_UUID(user_clean), payload=payload
            )
        )
    except Exception as e:
        return _service_error_payload(e)

    return {
        "success": True,
        "subscription_id": sub.get("id") if isinstance(sub, dict) else None,
        "status": sub.get("status") if isinstance(sub, dict) else "PENDING",
        "source_order_id": order_clean,
        "source_order_number": order.get("order_number"),
        "frequency": freq_norm,
        "start_date": start_norm,
        "end_date": end_norm,
        "items_count": len(sub_items),
        "message": (
            f"주문 {order.get('order_number') or order_clean[:8]} 의 품목을 그대로 정기배송 요청으로 보냈습니다. "
            f"(주기: {freq_norm}, 시작: {start_norm}) 상대방이 수락하면 자동 활성화됩니다."
        ),
    }
