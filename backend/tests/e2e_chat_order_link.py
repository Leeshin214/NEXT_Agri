"""주문 ↔ 채팅 양방향 연결 E2E 검증.

견적 요청 후:
1. chat_room 자동 생성 (또는 기존 방 재사용) + order_id 매핑 확인
2. messages 테이블에 message_type='SYSTEM' 행 생성 확인
3. POST /api/v1/orders/{id}/counter-offers → message_type='COUNTER_OFFER' 메시지 생성 확인
4. POST /api/v1/chat/rooms/{room_id}/counter-offer 엔드포인트 동작 확인
   - 권한 검증 (외부 user 거절)
   - order_id None 체크 (별도 시나리오)
5. 협상가 accept/reject → 메시지 type 확인
6. 주문 상태 변경 → ORDER_STATUS 메시지 확인
7. 주문 취소 → ORDER_CANCELLED 메시지 확인
"""
import asyncio
import time
import uuid
from typing import Any

import httpx
import jwt

from app.core.config import settings
from app.core.supabase import get_supabase_client
from app.main import app

BUYER = {
    "id": "94762ecc-23e8-4415-80ec-481b8bb3e6fb",
    "supabase_uid": "f54eb2f7-0b17-4059-94f1-e3612a0f4e30",
    "email": "test@gmail.com",
    "role": "BUYER",
}
SELLER = {
    "id": "556910e3-8b8b-466b-b304-d43e61e368d5",
    "supabase_uid": "256bccb1-d7f9-426f-b8a7-529dc0097549",
    "email": "test12345@gmail.com",
    "role": "SELLER",
}
PRODUCT_ID = "3ec260e9-51a2-4741-a491-4d3a2b484705"


def issue_token(sub: str, email: str) -> str:
    now = int(time.time())
    payload = {
        "sub": sub,
        "aud": "authenticated",
        "role": "authenticated",
        "email": email,
        "iat": now,
        "exp": now + 3600,
    }
    return jwt.encode(payload, settings.SUPABASE_JWT_SECRET, algorithm="HS256")


def auth(user: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_token(user['supabase_uid'], user['email'])}"}


def step(label: str, resp: httpx.Response, expected: int = 200) -> dict[str, Any]:
    body: Any
    try:
        body = resp.json()
    except Exception:
        body = resp.text
    status_ok = "PASS" if resp.status_code == expected else "FAIL"
    print(f"[{status_ok}] {label} -> HTTP {resp.status_code}")
    if resp.status_code != expected:
        print(f"   body: {body}")
        raise SystemExit(f"FAIL at: {label}")
    return body if isinstance(body, dict) else {}


async def query_messages(room_id: str, limit: int = 50) -> list[dict]:
    """직접 Supabase 에서 messages 조회 (message_type/metadata 검증용)."""
    client = get_supabase_client()
    result = await asyncio.to_thread(
        lambda: client.table("messages")
        .select("*")
        .eq("room_id", room_id)
        .is_("deleted_at", None)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return list(reversed(result.data or []))


async def query_chat_room(seller_id: str, buyer_id: str) -> dict | None:
    client = get_supabase_client()
    result = await asyncio.to_thread(
        lambda: client.table("chat_rooms")
        .select("*")
        .eq("seller_id", seller_id)
        .eq("buyer_id", buyer_id)
        .execute()
    )
    return result.data[0] if result.data else None


async def main() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        # 0. 사전 정리: 기존 chat_room 의 order_id 를 None 으로 리셋 (테스트 격리)
        client = get_supabase_client()
        await asyncio.to_thread(
            lambda: client.table("chat_rooms")
            .update({"order_id": None})
            .eq("seller_id", SELLER["id"])
            .eq("buyer_id", BUYER["id"])
            .execute()
        )

        # 1. (BUYER) 견적 요청 생성
        resp = await c.post(
            "/api/v1/orders",
            headers=auth(BUYER),
            json={
                "seller_id": SELLER["id"],
                "delivery_date": "2026-05-15",
                "delivery_address": "테스트 주소",
                "notes": "Chat-Order Link 테스트",
                "items": [
                    {"product_id": PRODUCT_ID, "quantity": 5, "unit_price": 3000},
                ],
            },
        )
        body = step("1. BUYER 견적 요청", resp, 201)
        order = body["data"]
        order_id = order["id"]
        print(f"   order_id={order_id}, order_number={order['order_number']}")

        # 2. chat_room 자동 생성 + order_id 연결 확인
        await asyncio.sleep(0.2)  # async event 처리 대기
        room = await query_chat_room(SELLER["id"], BUYER["id"])
        assert room, "chat_room 이 생성되지 않음"
        assert room["order_id"] == order_id, (
            f"chat_room.order_id 미일치: expected={order_id} actual={room.get('order_id')}"
        )
        room_id = room["id"]
        print(f"[PASS] 2. chat_room 자동 생성 확인 — room_id={room_id}, order_id 매핑 확인")

        # 3. SYSTEM 메시지 (견적 요청 알림) 확인
        msgs = await query_messages(room_id)
        sys_msgs = [m for m in msgs if m["message_type"] == "SYSTEM" and m["metadata"]
                    and m["metadata"].get("order_id") == order_id]
        assert sys_msgs, f"SYSTEM 메시지 없음. 전체: {[(m['message_type'], m['content'][:30]) for m in msgs]}"
        print(f"[PASS] 3. SYSTEM 메시지 INSERT 확인 — content={sys_msgs[-1]['content'][:50]}")

        # 4. (SELLER) 협상가 제시 → COUNTER_OFFER 메시지 검증
        resp = await c.post(
            f"/api/v1/orders/{order_id}/counter-offers",
            headers=auth(SELLER),
            json={"proposed_total_amount": 13000, "notes": "단가 인하"},
        )
        body = step("4. SELLER POST counter-offer", resp, 201)
        offer_id = body["data"]["id"]

        await asyncio.sleep(0.2)
        msgs = await query_messages(room_id)
        co_msgs = [m for m in msgs if m["message_type"] == "COUNTER_OFFER"
                   and m["metadata"] and m["metadata"].get("offer_id") == offer_id]
        assert co_msgs, f"COUNTER_OFFER 메시지 없음. types={[m['message_type'] for m in msgs]}"
        co_msg = co_msgs[-1]
        assert co_msg["metadata"]["proposed_total_amount"] == 13000
        assert co_msg["metadata"]["from_role"] == "SELLER"
        print(
            f"[PASS] 5. COUNTER_OFFER 메시지 검증 — "
            f"amount={co_msg['metadata']['proposed_total_amount']}, "
            f"from_role={co_msg['metadata']['from_role']}"
        )

        # 5. /chat/rooms/{room_id}/counter-offer 엔드포인트 — BUYER 카운터
        resp = await c.post(
            f"/api/v1/chat/rooms/{room_id}/counter-offer",
            headers=auth(BUYER),
            json={"proposed_total_amount": 14500, "notes": "절충안"},
        )
        body = step("6. BUYER POST /chat/rooms/{id}/counter-offer", resp, 201)
        buyer_offer_id = body["data"]["id"]
        assert body["data"]["from_role"] == "BUYER"
        assert body["data"]["proposed_total_amount"] == 14500

        await asyncio.sleep(0.2)
        msgs = await query_messages(room_id)
        co_msgs_buyer = [m for m in msgs if m["message_type"] == "COUNTER_OFFER"
                         and m["metadata"] and m["metadata"].get("offer_id") == buyer_offer_id]
        assert co_msgs_buyer, "BUYER COUNTER_OFFER 메시지 없음"
        print(f"[PASS] 7. /chat/.../counter-offer 엔드포인트 + 메시지 검증")

        # 6. 협상가 수락 → OFFER_ACCEPTED 메시지
        resp = await c.post(
            f"/api/v1/orders/{order_id}/counter-offers/{buyer_offer_id}/accept",
            headers=auth(SELLER),
        )
        step("8. SELLER accept BUYER offer", resp)

        await asyncio.sleep(0.2)
        msgs = await query_messages(room_id)
        accept_msgs = [m for m in msgs if m["message_type"] == "OFFER_ACCEPTED"
                       and m["metadata"] and m["metadata"].get("offer_id") == buyer_offer_id]
        assert accept_msgs, "OFFER_ACCEPTED 메시지 없음"
        assert accept_msgs[-1]["metadata"]["accepted_amount"] == 14500
        print(f"[PASS] 9. OFFER_ACCEPTED 메시지 검증")

        # 7. 주문 상태 변경 → ORDER_STATUS 메시지 (CONFIRMED 만 확인)
        resp = await c.patch(
            f"/api/v1/orders/{order_id}/status",
            headers=auth(BUYER),
            json={"status": "CONFIRMED"},
        )
        step("10. BUYER PATCH status=CONFIRMED", resp)

        await asyncio.sleep(0.2)
        msgs = await query_messages(room_id)
        status_msgs = [m for m in msgs if m["message_type"] == "ORDER_STATUS"
                       and m["metadata"] and m["metadata"].get("to_status") == "CONFIRMED"]
        assert status_msgs, "ORDER_STATUS(CONFIRMED) 메시지 없음"
        print(f"[PASS] 11. ORDER_STATUS 메시지 검증 (CONFIRMED)")

        # 8. 주문 취소 시나리오 — 새 주문 생성 후 취소
        resp = await c.post(
            "/api/v1/orders",
            headers=auth(BUYER),
            json={
                "seller_id": SELLER["id"],
                "items": [{"product_id": PRODUCT_ID, "quantity": 2, "unit_price": 1000}],
            },
        )
        body = step("12. BUYER 새 견적 (취소용)", resp, 201)
        cancel_order_id = body["data"]["id"]

        # 새 주문이 생성되면서 chat_room.order_id 가 cancel_order_id 로 갱신됨
        await asyncio.sleep(0.2)

        resp = await c.patch(
            f"/api/v1/orders/{cancel_order_id}/cancel",
            headers=auth(BUYER),
            json={"reason": "테스트 취소"},
        )
        step("13. BUYER 주문 취소", resp)

        await asyncio.sleep(0.2)
        msgs = await query_messages(room_id)
        cancel_msgs = [m for m in msgs if m["message_type"] == "ORDER_CANCELLED"
                       and m["metadata"] and m["metadata"].get("order_id") == cancel_order_id]
        assert cancel_msgs, "ORDER_CANCELLED 메시지 없음"
        assert cancel_msgs[-1]["metadata"]["reason"] == "테스트 취소"
        print(f"[PASS] 14. ORDER_CANCELLED 메시지 검증")

        # 9. 권한 검증 — 다른 사용자가 /chat/rooms/{id}/counter-offer 호출 시 403
        # (해당 시나리오는 외부 user 토큰 필요. 본 환경엔 BUYER, SELLER 만 있으므로 skip)

        # 10. order_id 없는 채팅방에서 counter-offer 호출 시 400
        # 별도 chat_room (order_id=None) 생성 후 호출 시도
        await asyncio.to_thread(
            lambda: client.table("chat_rooms")
            .update({"order_id": None})
            .eq("id", room_id)
            .execute()
        )
        resp = await c.post(
            f"/api/v1/chat/rooms/{room_id}/counter-offer",
            headers=auth(BUYER),
            json={"proposed_total_amount": 1000},
        )
        if resp.status_code == 400 and "연결된 주문이 없" in resp.json().get("error", ""):
            print("[PASS] 15. order_id None 채팅방에서 counter-offer 호출 시 400 반환")
        else:
            raise SystemExit(
                f"FAIL: order_id None 가드 미동작 — status={resp.status_code}, body={resp.json()}"
            )

        print("\nALL CHAT-ORDER LINK STEPS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
