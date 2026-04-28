"""주문/견적 E2E 시나리오 — buyer→견적→seller 협상→buyer 수락→상태 전환→완료."""
import asyncio
import time
import uuid
from typing import Any

import httpx
import jwt

from app.core.config import settings
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
PRODUCT_ID = "3ec260e9-51a2-4741-a491-4d3a2b484705"  # 사과 (test12345 소유)


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
    status_ok = "✅" if resp.status_code == expected else "❌"
    print(f"{status_ok} {label} → HTTP {resp.status_code}")
    if resp.status_code != expected:
        print(f"   body: {body}")
        raise SystemExit(f"FAIL at: {label}")
    return body if isinstance(body, dict) else {}


async def main() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        # 1. (BUYER) 견적 요청 생성
        resp = await c.post(
            "/api/v1/orders",
            headers=auth(BUYER),
            json={
                "seller_id": SELLER["id"],
                "delivery_date": "2026-05-15",
                "delivery_address": "서울시 강남구 테헤란로 123",
                "notes": "E2E 테스트 주문",
                "items": [
                    {"product_id": PRODUCT_ID, "quantity": 10, "unit_price": 5000, "notes": "특A급"},
                ],
            },
        )
        body = step("1. BUYER POST /orders (견적 요청)", resp, 201)
        order = body["data"]
        order_id = order["id"]
        assert order["status"] == "QUOTE_REQUESTED"
        assert order["total_amount"] == 50000, f"total={order['total_amount']}"
        print(f"   order_id={order_id}, total={order['total_amount']}")

        # 2. (BUYER) 견적 수정 (수량 변경)
        resp = await c.patch(
            f"/api/v1/orders/{order_id}",
            headers=auth(BUYER),
            json={"items": [{"product_id": PRODUCT_ID, "quantity": 12, "unit_price": 5000}]},
        )
        body = step("2. BUYER PATCH /orders/{id} (수정)", resp)
        assert body["data"]["total_amount"] == 60000, f"total={body['data']['total_amount']}"

        # 3. (SELLER) 협상가 제시 — total을 55000으로 낮춰 응답
        resp = await c.post(
            f"/api/v1/orders/{order_id}/counter-offers",
            headers=auth(SELLER),
            json={"proposed_total_amount": 55000, "notes": "수량 많아 단가 인하 제시"},
        )
        body = step("3. SELLER POST counter-offer", resp, 201)
        seller_offer_id = body["data"]["id"]
        assert body["data"]["status"] == "PENDING"
        assert body["data"]["from_role"] == "SELLER"

        # 3b. 주문 상태가 NEGOTIATING으로 자동 전환됐는지
        resp = await c.get(f"/api/v1/orders/{order_id}", headers=auth(BUYER))
        body = step("3b. GET /orders/{id} (상태 확인)", resp)
        assert body["data"]["status"] == "NEGOTIATING", f"status={body['data']['status']}"

        # 4. (BUYER) 카운터 — 58000 제시
        resp = await c.post(
            f"/api/v1/orders/{order_id}/counter-offers",
            headers=auth(BUYER),
            json={"proposed_total_amount": 58000, "notes": "58000원 어떠세요"},
        )
        body = step("4. BUYER POST counter-offer (카운터)", resp, 201)
        buyer_offer_id = body["data"]["id"]

        # 4b. 이전 SELLER 협상가가 SUPERSEDED로 마킹됐는지
        resp = await c.get(f"/api/v1/orders/{order_id}/counter-offers", headers=auth(BUYER))
        body = step("4b. GET counter-offers", resp)
        history = body["data"]
        seller_prev = next((o for o in history if o["id"] == seller_offer_id), None)
        assert seller_prev and seller_prev["status"] == "SUPERSEDED", f"prev status={seller_prev}"
        assert len(history) == 2

        # 5. (SELLER) BUYER 카운터 수락
        resp = await c.post(
            f"/api/v1/orders/{order_id}/counter-offers/{buyer_offer_id}/accept",
            headers=auth(SELLER),
        )
        body = step("5. SELLER accept BUYER offer", resp)
        assert body["data"]["status"] == "ACCEPTED"

        # 5b. orders.total_amount 가 58000으로 업데이트됐는지
        resp = await c.get(f"/api/v1/orders/{order_id}", headers=auth(BUYER))
        body = step("5b. GET /orders/{id} (total 확인)", resp)
        assert body["data"]["total_amount"] == 58000, f"total={body['data']['total_amount']}"

        # 6. (BUYER) NEGOTIATING → CONFIRMED (buyer 전용)
        resp = await c.patch(
            f"/api/v1/orders/{order_id}/status",
            headers=auth(BUYER),
            json={"status": "CONFIRMED"},
        )
        body = step("6. BUYER PATCH status=CONFIRMED", resp)
        assert body["data"]["status"] == "CONFIRMED"

        # 6b. SELLER가 CONFIRMED를 시도하면 거부돼야 함 (역할 가드)
        resp = await c.patch(
            f"/api/v1/orders/{order_id}/status",
            headers=auth(SELLER),
            json={"status": "QUOTE_REQUESTED"},  # 잘못된 전환
        )
        print(f"   (가드 테스트) SELLER → QUOTE_REQUESTED: HTTP {resp.status_code} (expect 4xx)")
        assert resp.status_code in (400, 403), f"가드 실패: {resp.status_code}"

        # 7. (SELLER) CONFIRMED → PREPARING
        resp = await c.patch(
            f"/api/v1/orders/{order_id}/status",
            headers=auth(SELLER),
            json={"status": "PREPARING"},
        )
        step("7. SELLER PATCH status=PREPARING", resp)

        # 8. (SELLER) PREPARING → SHIPPING
        resp = await c.patch(
            f"/api/v1/orders/{order_id}/status",
            headers=auth(SELLER),
            json={"status": "SHIPPING"},
        )
        step("8. SELLER PATCH status=SHIPPING", resp)

        # 9. (SELLER) SHIPPING → COMPLETED
        resp = await c.patch(
            f"/api/v1/orders/{order_id}/status",
            headers=auth(SELLER),
            json={"status": "COMPLETED"},
        )
        body = step("9. SELLER PATCH status=COMPLETED", resp)
        assert body["data"]["status"] == "COMPLETED"

        # 10. (BUYER) COMPLETED 이후 취소 시도 — 막혀야 함
        resp = await c.patch(
            f"/api/v1/orders/{order_id}/cancel",
            headers=auth(BUYER),
            json={"reason": "테스트 취소"},
        )
        print(f"   (가드 테스트) COMPLETED 이후 취소: HTTP {resp.status_code} (expect 4xx)")
        assert resp.status_code in (400, 403), f"COMPLETED 이후 취소 가드 실패: {resp.status_code}"

        # 11. 별도 주문으로 취소 플로우 테스트
        resp = await c.post(
            "/api/v1/orders",
            headers=auth(BUYER),
            json={
                "seller_id": SELLER["id"],
                "items": [{"product_id": PRODUCT_ID, "quantity": 5, "unit_price": 4000}],
            },
        )
        body = step("11. BUYER 새 견적 (취소용)", resp, 201)
        cancel_order_id = body["data"]["id"]

        resp = await c.patch(
            f"/api/v1/orders/{cancel_order_id}/cancel",
            headers=auth(BUYER),
            json={"reason": "단가 협상 결렬"},
        )
        body = step("11b. BUYER 취소", resp)
        assert body["data"]["status"] == "CANCELLED"
        assert body["data"]["cancellation_reason"] == "단가 협상 결렬"
        assert body["data"]["cancelled_at"] is not None
        assert body["data"]["cancelled_by"] == BUYER["id"]

        print("\n🎉 ALL E2E STEPS PASSED")
        print(f"   완료 주문: {order_id}")
        print(f"   취소 주문: {cancel_order_id}")


if __name__ == "__main__":
    asyncio.run(main())
