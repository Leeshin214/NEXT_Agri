"""offer status 메시지 동기화 검증 스크립트.

버그 시나리오:
  - SELLER 협상가 (offer A) 제시 → messages.metadata.status='PENDING'
  - BUYER 카운터 (offer B) → offer A 가 SUPERSEDED 로 바뀌지만 messages.metadata.status 는 stale
  - 따라서 프론트가 stale PENDING 카드를 그대로 표시

검증:
  1. 견적 요청
  2. SELLER 협상가 (offer A, PENDING) 제시 — messages.metadata.status == 'PENDING'
  3. BUYER 카운터 (offer B) — messages.metadata[offer_A].status == 'SUPERSEDED' (✓ 동기화)
  4. SELLER 가 offer B 수락 — messages.metadata[offer_B].status == 'ACCEPTED'
  5. (별도 주문) SELLER 협상가 → BUYER 거절 — messages.metadata.status == 'REJECTED'
"""
import asyncio
import time
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
    return jwt.encode(
        {
            "sub": sub,
            "aud": "authenticated",
            "role": "authenticated",
            "email": email,
            "iat": now,
            "exp": now + 3600,
        },
        settings.SUPABASE_JWT_SECRET,
        algorithm="HS256",
    )


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


async def fetch_offer_message_status(
    room_id: str, offer_id: str, *, retries: int = 5, delay: float = 0.3
) -> str | None:
    """messages 테이블에서 metadata.offer_id 가 일치하는 행의 metadata.status 반환.

    PostgREST 의 `metadata->>offer_id` 필터는 일부 환경에서 캐시/replication 지연으로
    빈 결과를 줄 수 있어, 채팅방 전체 COUNTER_OFFER/OFFER_ACCEPTED/OFFER_REJECTED 메시지를
    가져온 뒤 client-side 에서 offer_id 매칭으로 필터링한다.
    """
    client = get_supabase_client()
    last_status: str | None = None
    for _ in range(retries):
        result = await asyncio.to_thread(
            lambda: client.table("messages")
            .select("id, metadata, message_type, content, created_at")
            .eq("room_id", room_id)
            .in_("message_type", ["COUNTER_OFFER", "OFFER_ACCEPTED", "OFFER_REJECTED"])
            .order("created_at", desc=True)
            .limit(50)
            .execute()
        )
        matched = [
            r for r in (result.data or [])
            if (r.get("metadata") or {}).get("offer_id") == offer_id
            and r.get("message_type") == "COUNTER_OFFER"
        ]
        if matched:
            last_status = (matched[0].get("metadata") or {}).get("status")
            if last_status is not None:
                return last_status
        await asyncio.sleep(delay)
    return last_status


async def get_room_id(seller_id: str, buyer_id: str) -> str:
    client = get_supabase_client()
    result = await asyncio.to_thread(
        lambda: client.table("chat_rooms")
        .select("id")
        .eq("seller_id", seller_id)
        .eq("buyer_id", buyer_id)
        .execute()
    )
    assert result.data, "chat_room 없음"
    return result.data[0]["id"]


async def main() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        # 0. 사전 정리: 기존 chat_room 의 order_id 를 None 으로 리셋
        client = get_supabase_client()
        await asyncio.to_thread(
            lambda: client.table("chat_rooms")
            .update({"order_id": None})
            .eq("seller_id", SELLER["id"])
            .eq("buyer_id", BUYER["id"])
            .execute()
        )

        # ===========================================
        # 시나리오 1: PENDING -> SUPERSEDED -> ACCEPTED
        # ===========================================
        print("\n===== 시나리오 1: SUPERSEDED + ACCEPTED 동기화 =====")

        # 1. 견적 요청
        resp = await c.post(
            "/api/v1/orders",
            headers=auth(BUYER),
            json={
                "seller_id": SELLER["id"],
                "items": [{"product_id": PRODUCT_ID, "quantity": 5, "unit_price": 3000}],
            },
        )
        body = step("1. BUYER 견적 요청", resp, 201)
        order_id = body["data"]["id"]
        await asyncio.sleep(0.2)

        room_id = await get_room_id(SELLER["id"], BUYER["id"])
        print(f"   order_id={order_id}, room_id={room_id}")

        # 2. SELLER 협상가 (offer A, PENDING)
        resp = await c.post(
            f"/api/v1/orders/{order_id}/counter-offers",
            headers=auth(SELLER),
            json={"proposed_total_amount": 14000, "notes": "offer A"},
        )
        body = step("2. SELLER 협상가 (offer A)", resp, 201)
        offer_a_id = body["data"]["id"]
        await asyncio.sleep(0.2)

        # 3. messages.metadata.status == 'PENDING' 확인
        status_a = await fetch_offer_message_status(room_id, offer_a_id)
        assert status_a == "PENDING", f"offer A 초기 status 불일치: {status_a}"
        print(f"[PASS] 3. offer A 메시지 metadata.status == 'PENDING'")

        # 4. BUYER 카운터 (offer B) — offer A 는 SUPERSEDED 로 전환
        resp = await c.post(
            f"/api/v1/orders/{order_id}/counter-offers",
            headers=auth(BUYER),
            json={"proposed_total_amount": 13000, "notes": "offer B"},
        )
        body = step("4. BUYER 카운터 (offer B)", resp, 201)
        offer_b_id = body["data"]["id"]
        await asyncio.sleep(0.3)

        # 5. offer A 메시지의 status 가 SUPERSEDED 로 동기화됐는지 검증 ← 핵심 버그 케이스
        status_a_after = await fetch_offer_message_status(room_id, offer_a_id)
        assert status_a_after == "SUPERSEDED", (
            f"[BUG] offer A 메시지 metadata.status 가 SUPERSEDED 로 동기화되지 않음: "
            f"actual={status_a_after}"
        )
        print(f"[PASS] 5. offer A 메시지 metadata.status SUPERSEDED 동기화 확인 (핵심)")

        # 5b. offer B 메시지의 status 는 PENDING 이어야 함
        status_b = await fetch_offer_message_status(room_id, offer_b_id)
        assert status_b == "PENDING", f"offer B 초기 status 불일치: {status_b}"
        print(f"[PASS] 5b. offer B 메시지 metadata.status == 'PENDING'")

        # 6. SELLER 가 offer B 수락
        resp = await c.post(
            f"/api/v1/orders/{order_id}/counter-offers/{offer_b_id}/accept",
            headers=auth(SELLER),
        )
        step("6. SELLER offer B 수락", resp)
        await asyncio.sleep(0.3)

        # 7. offer B 메시지의 status 가 ACCEPTED 로 동기화됐는지 검증 ← 핵심 버그 케이스
        status_b_after = await fetch_offer_message_status(room_id, offer_b_id)
        assert status_b_after == "ACCEPTED", (
            f"[BUG] offer B 메시지 metadata.status 가 ACCEPTED 로 동기화되지 않음: "
            f"actual={status_b_after}"
        )
        print(f"[PASS] 7. offer B 메시지 metadata.status ACCEPTED 동기화 확인 (핵심)")

        # ===========================================
        # 시나리오 2: PENDING -> REJECTED 동기화
        # ===========================================
        print("\n===== 시나리오 2: REJECTED 동기화 =====")

        # 8. 별도 새 견적 요청 (이전 주문은 NEGOTIATING 상태로 남겨둔 채)
        resp = await c.post(
            "/api/v1/orders",
            headers=auth(BUYER),
            json={
                "seller_id": SELLER["id"],
                "items": [{"product_id": PRODUCT_ID, "quantity": 3, "unit_price": 2000}],
            },
        )
        body = step("8. BUYER 새 견적 (REJECTED 시나리오)", resp, 201)
        order2_id = body["data"]["id"]
        await asyncio.sleep(0.2)

        # 9. SELLER 협상가 (offer C, PENDING)
        resp = await c.post(
            f"/api/v1/orders/{order2_id}/counter-offers",
            headers=auth(SELLER),
            json={"proposed_total_amount": 5500, "notes": "offer C"},
        )
        body = step("9. SELLER 협상가 (offer C)", resp, 201)
        offer_c_id = body["data"]["id"]
        await asyncio.sleep(0.2)

        room2_id = await get_room_id(SELLER["id"], BUYER["id"])
        # 같은 buyer/seller 페어의 같은 room
        assert room2_id == room_id

        # 10. BUYER 가 offer C 거절
        resp = await c.post(
            f"/api/v1/orders/{order2_id}/counter-offers/{offer_c_id}/reject",
            headers=auth(BUYER),
        )
        step("10. BUYER offer C 거절", resp)
        await asyncio.sleep(0.3)

        # 11. offer C 메시지의 status 가 REJECTED 로 동기화됐는지 검증 ← 핵심 버그 케이스
        status_c_after = await fetch_offer_message_status(room2_id, offer_c_id)
        assert status_c_after == "REJECTED", (
            f"[BUG] offer C 메시지 metadata.status 가 REJECTED 로 동기화되지 않음: "
            f"actual={status_c_after}"
        )
        print(f"[PASS] 11. offer C 메시지 metadata.status REJECTED 동기화 확인 (핵심)")

        print("\n=========================================")
        print("ALL OFFER STATUS SYNC STEPS PASSED")
        print(f"  scenario 1 order: {order_id} (offer_a={offer_a_id}, offer_b={offer_b_id})")
        print(f"  scenario 2 order: {order2_id} (offer_c={offer_c_id})")
        print("=========================================")


if __name__ == "__main__":
    asyncio.run(main())
