"""캘린더 일정 관련 도구.

Cross-domain 의존: 없음 (calendar 도메인은 외부 helper 에 의존하지 않음).

calendar 도메인 4 개 도구 (groups=("calendar",)):
- get_calendar_events
- create_calendar_event
- update_calendar_event
- delete_calendar_event
"""
from __future__ import annotations

import re
from calendar import monthrange
from datetime import datetime, timezone
from typing import Optional

from app.core.supabase import get_supabase_client

from .._registry import tool


# ─────────────────────────────────────────────
# 캘린더 일정 관련 도구
# ─────────────────────────────────────────────

@tool(
    name="get_calendar_events",
    description="특정 연월의 캘린더 일정 목록을 조회한다. 해당 월 1일부터 말일까지의 일정을 반환한다.",
    parameters={
        "type": "object",
        "properties": {
            "user_id": {"type": "string", "description": "조회할 사용자의 UUID"},
            "year": {"type": "integer", "description": "조회할 연도 (예: 2026)"},
            "month": {"type": "integer", "description": "조회할 월 (1~12)"},
        },
        "required": ["user_id", "year", "month"],
    },
    groups=("calendar",),
)
def get_calendar_events(user_id: str, year: int, month: int) -> dict:
    """해당 월의 캘린더 일정을 조회한다.
    날짜 범위: YYYY-MM-01 ~ YYYY-MM-{말일}
    deleted_at IS NULL 조건 적용 (BUG-1 패턴: .is_("deleted_at", None) 사용)

    응답 평탄화 (응답 우선순위 정책 — 상품명·거래처명·날짜·상태 메인):
    - product_name: 첫 활성 상품명 또는 "{첫 상품명} 외 N건"
    - order_number, order_status
    - buyer_name, buyer_company, seller_name, seller_company
    임베딩 객체(orders 등)는 응답에서 제거 — LLM 토큰 낭비 방지.
    반환: {success, events, count}
    """
    try:
        year_str = re.sub(r'\D', '', str(year))
        month_str = re.sub(r'\D', '', str(month))

        year = int(year_str) if year_str else datetime.now().year
        month = int(month_str) if month_str else datetime.now().month
        supabase = get_supabase_client()

        last_day = monthrange(year, month)[1]
        date_from = f"{year:04d}-{month:02d}-01"
        date_to = f"{year:04d}-{month:02d}-{last_day:02d}"

        result = (
            supabase.table("calendar_events")
            .select(
                "id, title, event_type, event_date, description, order_id, created_at, "
                "orders(order_number, status, "
                "buyer:users!buyer_id(name,company_name), "
                "seller:users!seller_id(name,company_name), "
                "order_items(quantity, products(name)))"
            )
            .eq("user_id", user_id)
            .gte("event_date", date_from)
            .lte("event_date", date_to)
            .is_("deleted_at", None)
            .order("event_date")
            .execute()
        )

        rows = result.data or []
        flattened: list[dict] = []
        for row in rows:
            order_payload = row.pop("orders", None)

            # 기본값
            row["order_number"] = None
            row["order_status"] = None
            row["product_name"] = None
            row["buyer_name"] = None
            row["buyer_company"] = None
            row["seller_name"] = None
            row["seller_company"] = None

            if isinstance(order_payload, dict):
                row["order_number"] = order_payload.get("order_number")
                row["order_status"] = order_payload.get("status")

                buyer = order_payload.get("buyer") or {}
                seller = order_payload.get("seller") or {}
                row["buyer_name"] = buyer.get("name")
                row["buyer_company"] = buyer.get("company_name")
                row["seller_name"] = seller.get("name")
                row["seller_company"] = seller.get("company_name")

                items = order_payload.get("order_items") or []
                product_names: list[str] = []
                for item in items:
                    product = item.get("products") if isinstance(item, dict) else None
                    if not product:
                        continue
                    name = product.get("name")
                    if name:
                        product_names.append(name)
                if product_names:
                    if len(product_names) == 1:
                        row["product_name"] = product_names[0]
                    else:
                        row["product_name"] = f"{product_names[0]} 외 {len(product_names) - 1}건"

            flattened.append(row)

        return {
            "success": True,
            "events": flattened,
            "count": len(flattened),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "events": [], "count": 0}


@tool(
    name="create_calendar_event",
    description=(
        "캘린더에 새 일정을 등록한다. 호출 전 반드시 get_calendar_events로 동일 날짜 중복 여부를 확인한다. "
        "사용자가 시간을 명시한 경우(예: '오후 2시', '14:00', '오전 9시 30분')에는 반드시 start_time을 채워야 한다. "
        "시간이 명시되지 않았다면 start_time/end_time을 생략하여 종일 일정으로 등록한다."
    ),
    parameters={
        "type": "object",
        "properties": {
            "user_id": {"type": "string", "description": "일정 소유자의 UUID"},
            "title": {"type": "string", "description": "일정 제목"},
            "event_date": {"type": "string", "description": "일정 날짜 (YYYY-MM-DD)"},
            "event_type": {
                "type": "string",
                "description": "일정 유형: SHIPMENT | DELIVERY | MEETING | QUOTE_DEADLINE | ORDER",
                "enum": ["SHIPMENT", "DELIVERY", "MEETING", "QUOTE_DEADLINE", "ORDER"],
            },
            "description": {"type": "string", "description": "상세 설명"},
            "order_id": {"type": "string", "description": "연관된 주문 UUID"},
            "start_time": {
                "type": "string",
                "description": (
                    "시작 시각 (24시간제 HH:MM 형식, 예: '14:00', '09:30'). "
                    "사용자가 시간을 명시한 경우에만 채운다 — 생략하면 종일 일정으로 등록된다."
                ),
            },
            "end_time": {
                "type": "string",
                "description": (
                    "종료 시각 (24시간제 HH:MM 형식, 예: '15:30'). "
                    "start_time이 있을 때만 의미가 있다. 종료 시각이 명시되지 않으면 생략한다."
                ),
            },
        },
        "required": ["user_id", "title", "event_date", "event_type"],
    },
    groups=("calendar",),
)
def create_calendar_event(
    user_id: str,
    title: str,
    event_date: str,
    event_type: str,
    description: str = "",
    order_id: str = "",
    start_time: str = "",
    end_time: str = "",
) -> dict:
    """캘린더 일정을 등록한다.
    event_type: SHIPMENT | DELIVERY | MEETING | QUOTE_DEADLINE | ORDER | OTHER
    event_date: "YYYY-MM-DD" 형식
    start_time/end_time: "HH:MM" (24시간제). start_time 이 비어있으면 종일 일정으로 등록.
    order_id가 빈 문자열이면 NULL로 저장한다.
    반환: {success, event_id, title}
    """
    # 1. 유효성 검사 (기존과 동일)
    VALID_EVENT_TYPES = {"SHIPMENT", "DELIVERY", "MEETING", "QUOTE_DEADLINE", "ORDER", "OTHER"}
    if event_type not in VALID_EVENT_TYPES:
        return {
            "success": False,
            "error": f"유효하지 않은 event_type입니다. 허용값: {', '.join(sorted(VALID_EVENT_TYPES))}",
        }

    try:
        supabase = get_supabase_client()

        # order_id가 있다면 기존 일정이 있는지 확인하되, "event_type"도 같은지 확인
        if order_id:
            existing = (
                supabase.table("calendar_events")
                .select("id")
                .eq("order_id", order_id)
                .eq("event_type", event_type)
                .eq("user_id", user_id)
                .is_("deleted_at", None)  # 삭제되지 않은 것 중
                .execute()
            )

            # 같은 주문의 "같은 유형"의 일정이 이미 존재한다면? 새로 만들지 말고 업데이트!
            if existing.data:
                existing_event_id = existing.data[0]["id"]
                print(f"🕵️‍♂️ [System] 중복 일정 발견(ID: {existing_event_id}, 유형: {event_type}). 업데이트로 전환합니다.")

                return update_calendar_event(
                    user_id=user_id,
                    event_id=existing_event_id,
                    title=title,
                    event_date=event_date,
                    event_type=event_type,
                    description=description,
                    start_time=start_time or None,
                    end_time=end_time or None,
                )

        # 2. 신규 등록 로직 (주문은 같아도 '배송', '출하' 등 유형이 다르면 이쪽으로 빠져서 새로 생성됨)
        payload: dict = {
            "user_id": user_id,
            "title": title,
            "event_date": event_date,
            "event_type": event_type,
            "description": description or None,
            "order_id": order_id if order_id else None,
        }

        # 시간 명시 시: start_time/end_time 채우고 is_allday=False.
        # 미명시 시: 시간 필드 미추가 → DB DEFAULT(is_allday=true) 유지하여 종일 일정으로 등록.
        if start_time:
            payload["start_time"] = start_time
            payload["is_allday"] = False
            if end_time:
                payload["end_time"] = end_time

        result = supabase.table("calendar_events").insert(payload).execute()

        if not result.data:
            return {"success": False, "error": "일정 생성에 실패했습니다."}

        event = result.data[0]
        return {
            "success": True,
            "event_id": event["id"],
            "title": event.get("title", title),
            "message": "새로운 일정이 등록되었습니다."
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool(
    name="update_calendar_event",
    description=(
        "기존 캘린더 일정을 수정한다. 수정할 일정의 event_id와 변경할 내용만 전달한다. "
        "event_id를 모르면 먼저 get_calendar_events를 호출해서 찾아라. "
        "시간을 새로 지정/변경하려면 start_time(필요 시 end_time)을 채운다 — start_time이 채워지면 자동으로 종일 해제된다."
    ),
    parameters={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "event_id": {"type": "string", "description": "수정할 일정의 UUID"},
            "title": {"type": "string"},
            "event_date": {"type": "string", "description": "YYYY-MM-DD"},
            "event_type": {"type": "string"},
            "description": {"type": "string"},
            "start_time": {
                "type": "string",
                "description": "시작 시각 (24시간제 HH:MM, 예: '14:00'). 시간을 추가/변경할 때만 채운다.",
            },
            "end_time": {
                "type": "string",
                "description": "종료 시각 (24시간제 HH:MM, 예: '15:30'). start_time과 함께 사용한다.",
            },
        },
        "required": ["user_id", "event_id"],
    },
    groups=("calendar",),
)
def update_calendar_event(
    user_id: str,
    event_id: str,
    title: Optional[str] = None,
    event_date: Optional[str] = None,
    event_type: Optional[str] = None,
    description: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> dict:
    """캘린더 일정을 수정한다."""
    VALID_EVENT_TYPES = {"SHIPMENT", "DELIVERY", "MEETING", "QUOTE_DEADLINE", "ORDER", "OTHER"}
    if event_type and event_type not in VALID_EVENT_TYPES:
        return {"success": False, "error": f"유효하지 않은 event_type입니다."}

    try:
        supabase = get_supabase_client()
        check = (
            supabase.table("calendar_events")
            .select("id, user_id, title, event_type, order_id")
            .eq("id", event_id)
            .is_("deleted_at", None)
            .execute()
        )
        if not check.data:
            return {"success": False, "error": "해당 일정을 찾을 수 없습니다."}
        if check.data[0]["user_id"] != user_id:
            return {"success": False, "error": "권한 없음: 본인의 일정만 수정할 수 있습니다."}

        # 주문 상태(ORDER) 이벤트는 시스템 동기화 대상이므로, 날짜/타입을 바꿔치기하는 업데이트를 금지한다.
        # (배송/납품 일정은 별도의 DELIVERY/SHIPMENT 이벤트로 새로 등록해야 함)
        existing = check.data[0]
        if existing.get("order_id") and existing.get("event_type") == "ORDER":
            if event_date is not None or (event_type is not None and event_type != "ORDER"):
                return {
                    "success": False,
                    "error": "주문 상태(ORDER) 일정은 날짜/유형을 변경할 수 없습니다. 배송 일정은 새 일정으로 등록하세요.",
                }

        update_data: dict = {}
        if title is not None: update_data["title"] = title
        if event_date is not None: update_data["event_date"] = event_date
        if event_type is not None: update_data["event_type"] = event_type
        if description is not None: update_data["description"] = description
        # 시간 갱신: start_time 이 비어있지 않은 문자열이면 시간 등록 + is_allday=False.
        # None 또는 빈 문자열이면 시간 미변경 (기존 종일 여부 유지).
        if start_time:
            update_data["start_time"] = start_time
            update_data["is_allday"] = False
        if end_time:
            update_data["end_time"] = end_time

        if not update_data:
            return {"success": False, "error": "수정할 내용이 없습니다."}

        supabase.table("calendar_events").update(update_data).eq("id", event_id).execute()
        return {"success": True, "event_id": event_id, "message": f"일정 '{existing['title']}'이(가) 수정되었습니다."}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool(
    name="delete_calendar_event",
    description="기존 캘린더 일정을 삭제한다. 삭제할 일정의 event_id가 필요하다. 모르면 먼저 get_calendar_events를 호출해서 찾아라.",
    parameters={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "event_id": {"type": "string", "description": "삭제할 일정의 UUID"},
        },
        "required": ["user_id", "event_id"],
    },
    groups=("calendar",),
)
def delete_calendar_event(user_id: str, event_id: str) -> dict:
    """캘린더 일정을 삭제한다 (soft delete)."""
    try:
        supabase = get_supabase_client()
        check = supabase.table("calendar_events").select("id, user_id, title").eq("id", event_id).is_("deleted_at", None).execute()
        if not check.data:
            return {"success": False, "error": "해당 일정을 찾을 수 없습니다."}
        if check.data[0]["user_id"] != user_id:
            return {"success": False, "error": "권한 없음: 본인의 일정만 삭제할 수 있습니다."}

        now_utc = datetime.now(timezone.utc).isoformat()
        supabase.table("calendar_events").update({"deleted_at": now_utc}).eq("id", event_id).execute()
        return {"success": True, "event_id": event_id, "message": f"일정 '{check.data[0]['title']}'이(가) 삭제되었습니다."}
    except Exception as e:
        return {"success": False, "error": str(e)}
