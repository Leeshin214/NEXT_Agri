import asyncio
import time
from datetime import datetime, date, timedelta, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.security import verify_supabase_jwt
from app.core.supabase import get_supabase_client
from app.services.chat_service import chat_service
from app.websocket.connection_manager import manager

router = APIRouter()

# ─────────────────────────────────────────────
# 합의 감지 쿨다운 상태 (TTLCache — 메모리 누수 방지, 1시간 TTL)
# 서버 재시작 시 초기화 (의도된 동작)
# ─────────────────────────────────────────────

try:
    from cachetools import TTLCache  # type: ignore
    last_analysis: "dict[str, dict]" = TTLCache(maxsize=10000, ttl=3600)
except ImportError:
    # cachetools 미설치 시 fallback — 단순 dict + 수동 TTL 검사
    print("[WS] cachetools 미설치 — 기본 dict로 fallback (메모리 누수 가능)")
    last_analysis = {}


# 합의 처리 후 30분 쿨다운 (같은 거래의 중복 분석 방지용)
_CONSENSUS_COOLDOWN_SEC = 1800
# 합의 처리 후 짧은 디바운스 — 같은 거래의 즉각적 재분석 방지 (LLM 비용 절감)
# 이 시간 안에는 무조건 차단, 이 시간 이후엔 signature 비교로 같은 거래만 차단
_CONSENSUS_SHORT_DEBOUNCE_SEC = 60


def should_analyze(room_id: str) -> bool:
    """LLM 분석을 실행할지 판단한다.

    consensus_handled=True 인 경우:
    - 60초 이내: 무조건 차단 (디바운스)
    - 60초~30분: 분석 허용. _handle_consensus 가 signature 비교로 같은 거래는 건너뛴다.
      → 같은 채팅방에서 다른 거래 합의가 발생하면 즉시 처리 가능.
    - 30분 이후: 이전 상태 영향 없음, 무조건 허용.
    """
    last = last_analysis.get(room_id)
    if not last:
        return True
    elapsed = time.time() - last["time"]

    # 직전 합의가 처리된 경우
    if last.get("consensus_handled"):
        # 짧은 디바운스 안에는 무조건 차단
        if elapsed <= _CONSENSUS_SHORT_DEBOUNCE_SEC:
            return False
        # 60초~30분: signature 비교 위해 분석 허용 (실제 중복은 _handle_consensus 가 차단)
        # 30분 이후: 일반 동작 (아래 status 분기로 떨어짐)
        if elapsed <= _CONSENSUS_COOLDOWN_SEC:
            return True

    if last["status"] == "general":
        return elapsed > 60       # 일반 대화: 60초 쿨다운
    if last["status"] == "negotiating":
        return elapsed > 10       # 협상 중: 10초마다 재확인
    return True                   # consensus/rejected: 항상 재확인 (단, consensus_handled=True 시 위에서 차단)


# ─────────────────────────────────────────────
# 합의 자동 주문 — extracted 필드 검증
# ─────────────────────────────────────────────

def _coerce_int(value) -> int | None:
    """LLM이 '100' 같은 문자열로 줄 수 있는 정수 필드를 안전하게 변환한다."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (ValueError, TypeError, AttributeError):
        return None


# C-4: int4 상한 (Postgres int4 max = 2_147_483_647). 농산물 거래 도메인에 맞는 합리적 상한.
_MAX_QUANTITY = 10_000_000          # 최대 1천만 단위 (kg/box/개)
_MAX_PRICE_PER_UNIT = 100_000_000   # 최대 1억원/단위


def _validate_consensus_extracted(extracted: dict) -> tuple[bool, str, dict]:
    """
    create_order 진입 전 extracted 필드 검증.

    검증 항목:
    - product: 비어있지 않은 문자열
    - quantity: int > 0, ≤ _MAX_QUANTITY (LLM 환각/오타로 비현실적 큰 값 차단)
    - price_per_unit: int > 0, ≤ _MAX_PRICE_PER_UNIT
    - delivery_date: ISO date 파싱 가능 + 오늘 이후

    반환: (valid, reason, normalized)
    - valid=True 시 normalized 에 정수/날짜 정규화된 dict 반환
    """
    product = extracted.get("product")
    if not isinstance(product, str) or not product.strip():
        return False, "상품 정보가 비어있습니다.", {}

    quantity = _coerce_int(extracted.get("quantity"))
    if quantity is None or quantity <= 0:
        return False, "수량 정보가 정확하지 않습니다.", {}
    if quantity > _MAX_QUANTITY:
        return (
            False,
            f"수량이 허용 한도를 초과했습니다 (최대 {_MAX_QUANTITY:,}).",
            {},
        )

    price_per_unit = _coerce_int(extracted.get("price_per_unit"))
    if price_per_unit is None or price_per_unit <= 0:
        return False, "단가 정보가 정확하지 않습니다.", {}
    if price_per_unit > _MAX_PRICE_PER_UNIT:
        return (
            False,
            f"단가가 허용 한도를 초과했습니다 (최대 {_MAX_PRICE_PER_UNIT:,}원).",
            {},
        )

    delivery_date_raw = extracted.get("delivery_date")
    if not delivery_date_raw or not isinstance(delivery_date_raw, str):
        return False, "납기일 정보가 비어있습니다.", {}
    try:
        parsed_date = date.fromisoformat(delivery_date_raw)
    except (ValueError, TypeError):
        return False, "납기일 형식이 올바르지 않습니다 (YYYY-MM-DD).", {}

    today = datetime.now(timezone.utc).date()
    if parsed_date < today:
        return False, "납기일이 과거 날짜입니다.", {}

    return True, "", {
        "product": product.strip(),
        "quantity": quantity,
        "price_per_unit": price_per_unit,
        "delivery_date": parsed_date.isoformat(),
    }


async def _broadcast_system_message(
    room_id: str, content: str, sender_id_fallback: str
) -> None:
    """시스템 메시지를 DB INSERT + WebSocket broadcast 한다.

    DB INSERT 실패 시에도 broadcast 는 시도한다 (채팅 흐름 우선).
    broadcast payload 에 message_id 를 포함하여 프론트가 메시지 추적 가능하도록 한다.

    sender_id_fallback 가 빈 문자열/None 인 경우 messages.sender_id NOT NULL FK 제약상
    DB INSERT 가 불가하므로 INSERT 는 skip 하고 broadcast 만 진행한다.
    """
    from uuid import UUID

    inserted_id: str | None = None
    inserted_created_at: str | None = None

    # 1) sender_id_fallback 빈 문자열 가드 — 빈 값이면 INSERT skip
    sender_clean = (sender_id_fallback or "").strip()
    if not sender_clean:
        print(
            f"[system_msg] sender_id_fallback 비어있음 → DB INSERT skip "
            f"(broadcast 만 진행). room_id={room_id}"
        )
    else:
        # 2) UUID 변환 시도 (실패 시 INSERT skip + 로깅)
        try:
            sender_uuid = UUID(sender_clean)
        except (ValueError, TypeError) as e:
            print(
                f"[system_msg] sender_id_fallback UUID 변환 실패 → DB INSERT skip: "
                f"value={sender_clean!r} error={type(e).__name__}: {e}"
            )
        else:
            try:
                message = await chat_service.send_system_message(
                    room_id=UUID(room_id),
                    content=content,
                    sender_id=sender_uuid,
                )
                if message:
                    inserted_id = str(message.get("id", ""))
                    inserted_created_at = message.get("created_at")
            except Exception as e:
                print(
                    f"[system_msg] DB INSERT 실패 (broadcast 만 진행): "
                    f"{type(e).__name__}: {e}"
                )

    # 3) broadcast (INSERT 성공/실패 무관하게 실행)
    payload = {
        "type": "system",
        "content": content,
        "room_id": room_id,
    }
    if inserted_id:
        payload["id"] = inserted_id
    if inserted_created_at:
        payload["created_at"] = inserted_created_at

    try:
        await manager.broadcast(room_id, payload)
    except Exception as e:
        print(f"[system_msg] broadcast 실패: {type(e).__name__}: {e}")


def _check_recent_duplicate_order(
    buyer_id: str, seller_id: str, product_id: str, delivery_date: str
) -> bool:
    """
    동일 (buyer, seller, product, delivery_date) 조합 주문이 최근 1시간 이내 존재하는지 확인.

    note 컬럼이 없으면 order_items + orders 테이블 조인으로 product_id 매칭.
    True 반환 시 합의 자동 주문 skip.
    """
    try:
        supabase = get_supabase_client()
        # 최근 1시간 기준
        one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

        # 동일 buyer/seller/delivery_date orders 조회
        orders_result = (
            supabase.table("orders")
            .select("id")
            .eq("buyer_id", buyer_id)
            .eq("seller_id", seller_id)
            .eq("delivery_date", delivery_date)
            .gte("created_at", one_hour_ago)
            .is_("deleted_at", None)
            .execute()
        )
        order_ids = [o["id"] for o in (orders_result.data or [])]
        if not order_ids:
            return False

        # 해당 orders 중 product_id 매칭되는 order_items 존재 여부
        items_result = (
            supabase.table("order_items")
            .select("id")
            .in_("order_id", order_ids)
            .eq("product_id", product_id)
            .limit(1)
            .execute()
        )
        return bool(items_result.data)
    except Exception as e:
        print(f"[consensus dup-check] 조회 실패 (skip 으로 간주 안 함): {type(e).__name__}: {e}")
        return False


# ─────────────────────────────────────────────
# 합의 감지 후속 처리
# ─────────────────────────────────────────────

async def _handle_consensus(room_id: str, result: dict) -> bool:
    """
    consensus 분기:
    1) signature 비교 — 직전 처리된 합의와 동일하면 skip (같은 거래 중복 방지)
    2) extracted 필드 검증 (수량/단가/납기일/상품)
    3) product 이름으로 product_id 매칭
    4) 최근 1시간 중복 주문 idempotency 체크
    5) create_order 자동 생성 (status=QUOTE_REQUESTED, notes=[AI 합의 자동])
    6) 양쪽 사용자에게 create_calendar_event (DELIVERY)
    7) 채팅방 시스템 메시지 broadcast + DB INSERT

    반환: 합의 처리 성공 시 True (호출처에서 consensus_handled=True 마킹용).
    검증 실패/중복/오류 시 False.
    """
    from app.services.agent_tools import (
        create_calendar_event,
        create_order,
        _find_product_by_name,
    )

    extracted = result.get("extracted") or {}
    buyer_id: str = extracted.get("buyer_id", "")
    seller_id: str = extracted.get("seller_id", "")
    confidence = result.get("confidence")
    unit: str = extracted.get("unit") or ""

    # 시스템 메시지 fallback sender — chat_room 의 seller_id 사용
    sender_fallback = seller_id or buyer_id

    # 1) signature 비교 — 직전 처리된 합의와 동일하면 skip
    current_signature = (
        f"{buyer_id}|{seller_id}|"
        f"{extracted.get('product', '')}|"
        f"{extracted.get('delivery_date', '')}"
    )
    last = last_analysis.get(room_id)
    if (
        last
        and last.get("consensus_handled")
        and last.get("consensus_signature") == current_signature
    ):
        print(f"[consensus] 동일 거래 signature 일치 → skip (room={room_id})")
        return False

    # 2) extracted 필드 검증
    valid, reason, normalized = _validate_consensus_extracted(extracted)
    if not valid:
        print(f"[consensus] 검증 실패 ({reason}) → 자동 주문 보류")
        await _broadcast_system_message(
            room_id,
            (
                "⚠️ AI가 합의를 감지했지만 주문 정보(수량/단가/납기일)가 불완전해 "
                f"자동 생성을 보류했습니다. ({reason}) 채팅에서 정확히 정리해 주세요."
            ),
            sender_fallback,
        )
        return False

    product_name = normalized["product"]
    quantity = normalized["quantity"]
    price_per_unit = normalized["price_per_unit"]
    delivery_date = normalized["delivery_date"]

    # 2) product_id 매칭
    product_id: str | None = None
    resolved_product_name: str = product_name
    try:
        supabase = get_supabase_client()
        found = await asyncio.to_thread(
            _find_product_by_name, supabase, product_name, seller_id
        )
        if found:
            product_id = found["id"]
            resolved_product_name = found.get("name", product_name)
    except Exception as e:
        print(f"[consensus] product 매칭 실패: {e}")

    if not product_id:
        await _broadcast_system_message(
            room_id,
            "AI가 거래 합의를 감지했으나 상품 정보를 특정하지 못해 주문 자동 생성을 건너뜁니다.",
            sender_fallback,
        )
        return False

    # 3) 중복 주문 idempotency 체크
    is_dup = await asyncio.to_thread(
        _check_recent_duplicate_order, buyer_id, seller_id, product_id, delivery_date
    )
    if is_dup:
        await _broadcast_system_message(
            room_id,
            "이미 동일 거래의 주문이 존재합니다. 자동 주문 생성을 건너뜁니다.",
            sender_fallback,
        )
        # 중복은 성공적으로 처리된 것으로 간주 → 쿨다운 적용
        return True

    # 4) create_order
    order_id: str | None = None
    notes_text = f"[AI 합의 자동] confidence={confidence} (AgenticPay)"
    try:
        order_result = await asyncio.to_thread(
            create_order,
            buyer_id,
            seller_id,
            product_id,
            quantity,
            price_per_unit,
            delivery_date,
            None,                # delivery_address
            notes_text,
        )
        if order_result.get("success"):
            order = order_result.get("order") or {}
            order_id = order.get("id")
            print(f"[consensus] 주문 자동 생성: order_id={order_id}")
        else:
            print(f"[consensus] 주문 생성 실패: {order_result.get('error')}")
            await _broadcast_system_message(
                room_id,
                "AI 합의는 감지했으나 주문 자동 생성에 실패했습니다.",
                sender_fallback,
            )
            return False
    except Exception as e:
        print(f"[consensus] create_order 예외: {e}")
        await _broadcast_system_message(
            room_id,
            "AI 합의는 감지했으나 주문 생성 처리 중 오류가 발생했습니다.",
            sender_fallback,
        )
        return False

    # 5) 양쪽 사용자에게 캘린더 일정 등록
    if delivery_date and order_id:
        cal_title = f"배송: {resolved_product_name}"
        for uid in [buyer_id, seller_id]:
            if not uid:
                continue
            try:
                await asyncio.to_thread(
                    create_calendar_event,
                    uid,
                    cal_title,
                    delivery_date,
                    "DELIVERY",
                    f"AI 합의 감지 자동 등록 — {quantity}{unit} {price_per_unit}원/단위",
                    order_id,
                )
            except Exception as e:
                print(f"[consensus] create_calendar_event 실패 user={uid}: {e}")

    # 6) 시스템 메시지 broadcast + DB INSERT
    await _broadcast_system_message(
        room_id,
        (
            f"AI가 거래 합의를 감지하여 주문을 자동 생성했습니다. "
            f"({resolved_product_name} {quantity}{unit}, "
            f"{price_per_unit:,}원/단위, 납기 {delivery_date}) "
            f"[AgenticPay 기반]"
        ),
        sender_fallback,
    )
    return True


async def _handle_rejected(room_id: str, result: dict) -> None:
    """
    rejected 분기:
    - 채팅방에는 시스템 메시지 broadcast (DB INSERT 포함)
    - buyer/seller 각자에게 send_private_message 로 대체 거래처 제안
    """
    from app.services.agent_tools import find_alternative_partners

    extracted = result.get("extracted") or {}
    buyer_id: str = extracted.get("buyer_id", "")
    seller_id: str = extracted.get("seller_id", "")
    sender_fallback = seller_id or buyer_id

    # product 이름에서 category 추론 (간단 매핑 — 알 수 없으면 "VEGETABLE" 기본값)
    product_name: str = extracted.get("product", "")
    category = _infer_category(product_name)

    try:
        alternatives_result = await asyncio.to_thread(
            find_alternative_partners,
            buyer_id,
            "BUYER",
            category,
            "협상 결렬",
        )
        alternatives = alternatives_result.get("alternatives", [])
    except Exception as e:
        print(f"[rejected] find_alternative_partners 실패: {e}")
        alternatives = []

    payload = {
        "type": "alternative_partners_suggestion",
        "message": "거래가 성사되지 않았습니다. 대체 거래처를 찾아드릴까요?",
        "alternatives": alternatives,
        "category": category,
    }

    for uid in [buyer_id, seller_id]:
        if uid:
            try:
                await manager.send_private_message(uid, payload)
            except Exception as e:
                print(f"[rejected] send_private_message 실패 user={uid}: {e}")

    # 채팅방 시스템 메시지 broadcast + DB INSERT
    if sender_fallback:
        await _broadcast_system_message(
            room_id,
            "AI가 협상 결렬을 감지했습니다. 양측에 대체 거래처 추천을 전송했습니다.",
            sender_fallback,
        )


def _infer_category(product_name: str) -> str:
    """상품명으로부터 카테고리를 간단히 추론한다. 매칭 실패 시 VEGETABLE 반환."""
    name = product_name.lower()
    mapping = {
        "사과": "FRUIT", "배": "FRUIT", "딸기": "FRUIT", "포도": "FRUIT",
        "귤": "FRUIT", "오렌지": "FRUIT", "복숭아": "FRUIT", "수박": "FRUIT",
        "감자": "VEGETABLE", "양파": "VEGETABLE", "배추": "VEGETABLE",
        "당근": "VEGETABLE", "고추": "VEGETABLE", "마늘": "VEGETABLE",
        "토마토": "VEGETABLE", "오이": "VEGETABLE", "호박": "VEGETABLE",
        "쌀": "GRAIN", "보리": "GRAIN", "콩": "GRAIN",
    }
    for keyword, cat in mapping.items():
        if keyword in name:
            return cat
    return "VEGETABLE"


# ─────────────────────────────────────────────
# WebSocket 인증 헬퍼
# ─────────────────────────────────────────────

async def _get_user_from_token(token: str) -> dict | None:
    """JWT 토큰을 검증하고 users 테이블에서 사용자를 조회한다."""
    try:
        payload = await verify_supabase_jwt(token)
        supabase_uid = payload.get("sub")
        if not supabase_uid:
            print(f"[WS AUTH] sub 없음 in payload")
            return None

        client = get_supabase_client()
        result = await asyncio.to_thread(
            lambda: client.table("users")
            .select("*")
            .eq("supabase_uid", supabase_uid)
            .single()
            .execute()
        )
        if not result.data:
            print(f"[WS AUTH] 사용자 없음: supabase_uid={supabase_uid}")
        return result.data or None
    except Exception as e:
        print(f"[WS AUTH] 인증 실패: {type(e).__name__}: {e}")
        return None


async def _get_room(room_id: str) -> dict | None:
    """채팅방 조회"""
    try:
        client = get_supabase_client()
        result = await asyncio.to_thread(
            lambda: client.table("chat_rooms")
            .select("*")
            .eq("id", room_id)
            .single()
            .execute()
        )
        if not result.data:
            print(f"[WS ROOM] 채팅방 없음: room_id={room_id}")
        return result.data or None
    except Exception as e:
        print(f"[WS ROOM] 조회 실패: {type(e).__name__}: {e}")
        return None


# ─────────────────────────────────────────────
# WebSocket 엔드포인트
# ─────────────────────────────────────────────

@router.websocket("/ws/chat/{room_id}")
async def websocket_chat(websocket: WebSocket, room_id: str):
    """
    WebSocket 채팅 엔드포인트
    URL: /ws/chat/{room_id}?token={jwt_token}

    수신 형식: {"type": "message", "content": "내용"}
    송신 형식: {"type": "message", "id": "...", "room_id": "...",
               "sender_id": "...", "content": "...",
               "is_read": false, "created_at": "ISO8601"}
    시스템 형식: {"type": "system", "id": "...", "room_id": "...",
                "content": "...", "created_at": "..."}
    개별 형식: {"type": "alternative_partners_suggestion", ...}
    오류 형식: {"type": "error", "message": "에러메시지"}
    """
    # 1. query param에서 token 추출
    token = websocket.query_params.get("token")
    if not token:
        print(f"[WS] 토큰 없음 → close(4001)")
        await websocket.close(code=4001)
        return

    # 2. JWT 검증 및 사용자 조회
    user = await _get_user_from_token(token)
    if not user:
        print(f"[WS] 사용자 인증 실패 → close(4001)")
        await websocket.close(code=4001)
        return

    # 3. 채팅방 존재 여부 + 참여자 확인
    room = await _get_room(room_id)
    if not room:
        print(f"[WS] 채팅방 없음: room_id={room_id} → close(4004)")
        await websocket.close(code=4004)
        return

    user_id = str(user["id"])
    if user_id not in (str(room["seller_id"]), str(room["buyer_id"])):
        print(f"[WS] 참여자 아님: user_id={user_id}, seller={room['seller_id']}, buyer={room['buyer_id']} → close(4003)")
        await websocket.close(code=4003)
        return

    # 4. 연결 수락 (user_id 매핑 포함)
    print(f"[WS] 연결 수락: user_id={user_id}, room_id={room_id}")
    await manager.connect(room_id, websocket, user_id)

    try:
        # 5. 메시지 수신 루프
        while True:
            data = await websocket.receive_json()

            if data.get("type") != "message":
                await websocket.send_json(
                    {"type": "error", "message": "지원하지 않는 메시지 유형입니다."}
                )
                continue

            content = data.get("content", "").strip()
            if not content:
                await websocket.send_json(
                    {"type": "error", "message": "메시지 내용이 비어있습니다."}
                )
                continue

            # 6. DB 저장
            from uuid import UUID

            message = await chat_service.send_message(
                room_id=UUID(room_id),
                sender_id=UUID(user_id),
                content=content,
            )

            # 7. 방의 모든 연결에 브로드캐스트
            broadcast_payload = {
                "type": "message",
                "id": str(message["id"]),
                "room_id": str(message["room_id"]),
                "sender_id": str(message["sender_id"]),
                "content": message["content"],
                "is_read": message["is_read"],
                "created_at": message["created_at"],
            }
            await manager.broadcast(room_id, broadcast_payload)

            # 8. 합의 감지 백그라운드 실행 (쿨다운 적용)
            if should_analyze(room_id):
                try:
                    from app.services.agent_tools import analyze_chat_consensus

                    # caller_user_id 전달 — analyze_chat_consensus 내부에서 권한 검증
                    result = await asyncio.to_thread(
                        analyze_chat_consensus, room_id, 10, user_id
                    )
                    status = result.get("status", "general")

                    extracted_local = result.get("extracted") or {}
                    consensus_signature = (
                        f"{extracted_local.get('buyer_id', '')}|"
                        f"{extracted_local.get('seller_id', '')}|"
                        f"{extracted_local.get('product', '')}|"
                        f"{extracted_local.get('delivery_date', '')}"
                    )

                    print(f"[WS] 합의 감지: room_id={room_id}, status={status}")

                    if status == "consensus":
                        # C-3: 낙관적 락 — _handle_consensus 진입 전 consensus_handled=True 마킹
                        # 이로써 같은 합의에 대한 동시 LLM 호출/시스템 메시지 중복을 방지한다.
                        # 실패 시 except 블록에서 False 로 되돌린다.
                        last_analysis[room_id] = {
                            "time": time.time(),
                            "status": status,
                            "consensus_handled": True,
                            "consensus_signature": consensus_signature,
                        }
                        try:
                            handled = await _handle_consensus(room_id, result)
                            if not handled:
                                # 검증 실패/중복/오류 → 락 해제 (다음 합의 분석 허용)
                                last_analysis[room_id] = {
                                    "time": time.time(),
                                    "status": status,
                                    "consensus_handled": False,
                                    "consensus_signature": consensus_signature,
                                }
                        except Exception as inner_e:
                            # _handle_consensus 안에서 예외 발생 시에도 락 해제
                            print(
                                f"[WS] _handle_consensus 예외 → 락 해제: "
                                f"{type(inner_e).__name__}: {inner_e}"
                            )
                            last_analysis[room_id] = {
                                "time": time.time(),
                                "status": status,
                                "consensus_handled": False,
                                "consensus_signature": consensus_signature,
                            }
                    else:
                        # consensus 가 아닌 경우는 락 마킹 없이 단순 기록만
                        last_analysis[room_id] = {
                            "time": time.time(),
                            "status": status,
                            "consensus_handled": False,
                            "consensus_signature": consensus_signature,
                        }
                        if status == "rejected":
                            await _handle_rejected(room_id, result)
                        # negotiating / general: 액션 없음

                except Exception as e:
                    # 합의 감지 실패는 채팅 흐름을 막지 않음
                    print(f"[WS] 합의 감지 처리 오류 (무시): {type(e).__name__}: {e}")

    except WebSocketDisconnect:
        # 9. 연결 끊김 처리
        manager.disconnect(room_id, websocket, user_id)
    except Exception as e:
        # 예상치 못한 오류 — 연결 정리 후 종료
        manager.disconnect(room_id, websocket, user_id)
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
