"""주문 응답에 join 필드(buyer_name/seller_name/product_name 등)가 채워지는지 검증."""
import asyncio
import time

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


def assert_join_fields(label: str, order: dict) -> None:
    """OrderResponse 안에 join 필드들이 채워졌는지 검증."""
    print(f"\n[{label}] order_id={order['id']}")
    # buyer/seller join 필드
    print(f"  buyer_name={order.get('buyer_name')}, buyer_company={order.get('buyer_company')}")
    print(f"  seller_name={order.get('seller_name')}, seller_company={order.get('seller_company')}")
    assert order.get("buyer_name") is not None, f"{label}: buyer_name is None"
    assert order.get("seller_name") is not None, f"{label}: seller_name is None"
    # company_name 은 회원가입 시 채워졌을 수 있음 — None 허용이지만 운영 데이터에서는 채워져 있어야 함
    assert order.get("buyer_company") is not None, f"{label}: buyer_company is None (현재 운영 데이터 기준)"
    assert order.get("seller_company") is not None, f"{label}: seller_company is None"

    # items 안의 product join 필드
    items = order.get("items") or []
    assert len(items) > 0, f"{label}: items 비어있음"
    for i, item in enumerate(items):
        print(f"  item[{i}] product_name={item.get('product_name')}, "
              f"product_unit={item.get('product_unit')}, "
              f"product_category={item.get('product_category')}")
        assert item.get("product_name") is not None, f"{label}: item[{i}] product_name is None"
        assert item.get("product_unit") is not None, f"{label}: item[{i}] product_unit is None"
        assert item.get("product_category") is not None, f"{label}: item[{i}] product_category is None"


async def main() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        # 1. (BUYER) 견적 요청 — 응답 즉시 join 필드 검증
        resp = await c.post(
            "/api/v1/orders",
            headers=auth(BUYER),
            json={
                "seller_id": SELLER["id"],
                "delivery_date": "2026-05-20",
                "delivery_address": "서울시 강남구",
                "notes": "join 필드 테스트",
                "items": [
                    {"product_id": PRODUCT_ID, "quantity": 7, "unit_price": 5000},
                ],
            },
        )
        assert resp.status_code == 201, f"create_order failed: {resp.status_code} {resp.text}"
        order = resp.json()["data"]
        assert_join_fields("create_order 직후", order)
        order_id = order["id"]

        # 2. GET /orders/{id} — 상세 조회 join 필드
        resp = await c.get(f"/api/v1/orders/{order_id}", headers=auth(BUYER))
        assert resp.status_code == 200
        assert_join_fields("get_order", resp.json()["data"])

        # 3. GET /orders — 목록 조회 join 필드
        resp = await c.get("/api/v1/orders", headers=auth(BUYER))
        assert resp.status_code == 200
        orders = resp.json()["data"]
        assert len(orders) > 0, "list_orders 결과 비어있음"
        # 방금 만든 주문 찾기
        found = next((o for o in orders if o["id"] == order_id), None)
        assert found is not None, "list_orders 결과에 방금 만든 주문 없음"
        assert_join_fields("list_orders[match]", found)

        # 4. PATCH /orders/{id} — 수정 응답 join 필드
        resp = await c.patch(
            f"/api/v1/orders/{order_id}",
            headers=auth(BUYER),
            json={"notes": "수정된 메모"},
        )
        assert resp.status_code == 200
        assert_join_fields("update_order", resp.json()["data"])

        # 5. SELLER가 즉시 CONFIRMED로 전환 — 변경 1 검증 (SELLER도 가능)
        resp = await c.patch(
            f"/api/v1/orders/{order_id}/status",
            headers=auth(SELLER),
            json={"status": "CONFIRMED"},
        )
        assert resp.status_code == 200, \
            f"SELLER → CONFIRMED 가 실패 (변경 1 정책 미적용): {resp.status_code} {resp.text}"
        assert_join_fields("SELLER가 CONFIRMED 전환", resp.json()["data"])
        print("  ✅ SELLER가 QUOTE_REQUESTED → CONFIRMED 전환 성공 (변경 1)")

        # 6. SELLER → PREPARING (SELLER만 가능 — 그대로)
        resp = await c.patch(
            f"/api/v1/orders/{order_id}/status",
            headers=auth(SELLER),
            json={"status": "PREPARING"},
        )
        assert resp.status_code == 200

        # 7. BUYER가 PREPARING → SHIPPING 시도 (BUYER 거부)
        resp = await c.patch(
            f"/api/v1/orders/{order_id}/status",
            headers=auth(BUYER),
            json={"status": "SHIPPING"},
        )
        assert resp.status_code == 403, \
            f"BUYER → SHIPPING 가 거부되지 않음 (변경 1 정책 미적용): {resp.status_code}"
        print("  ✅ BUYER → PREPARING→SHIPPING 거부됨 (SELLER 전용 유지)")

        # 8. SELLER → SHIPPING
        resp = await c.patch(
            f"/api/v1/orders/{order_id}/status",
            headers=auth(SELLER),
            json={"status": "SHIPPING"},
        )
        assert resp.status_code == 200

        # 9. BUYER가 SHIPPING → COMPLETED (변경 1 — BUYER도 가능)
        resp = await c.patch(
            f"/api/v1/orders/{order_id}/status",
            headers=auth(BUYER),
            json={"status": "COMPLETED"},
        )
        assert resp.status_code == 200, \
            f"BUYER → COMPLETED 실패 (변경 1 정책 미적용): {resp.status_code} {resp.text}"
        body = resp.json()["data"]
        assert body["status"] == "COMPLETED"
        assert_join_fields("BUYER가 COMPLETED 전환", body)
        print("  ✅ BUYER가 SHIPPING → COMPLETED 전환 성공 (변경 1)")

        # 10. 별도 주문으로 SELLER가 직접 NEGOTIATING → CONFIRMED 검증
        resp = await c.post(
            "/api/v1/orders",
            headers=auth(BUYER),
            json={
                "seller_id": SELLER["id"],
                "items": [{"product_id": PRODUCT_ID, "quantity": 3, "unit_price": 5000}],
            },
        )
        assert resp.status_code == 201
        neg_order_id = resp.json()["data"]["id"]
        # 협상 진입
        resp = await c.post(
            f"/api/v1/orders/{neg_order_id}/counter-offers",
            headers=auth(SELLER),
            json={"proposed_total_amount": 14000},
        )
        assert resp.status_code == 201
        # SELLER가 NEGOTIATING → CONFIRMED (변경 1)
        resp = await c.patch(
            f"/api/v1/orders/{neg_order_id}/status",
            headers=auth(SELLER),
            json={"status": "CONFIRMED"},
        )
        assert resp.status_code == 200, \
            f"SELLER NEGOTIATING → CONFIRMED 실패: {resp.status_code} {resp.text}"
        print("  ✅ SELLER가 NEGOTIATING → CONFIRMED 전환 성공 (변경 1)")

        print("\n🎉 ALL JOIN-FIELD + ROLE-GUARD STEPS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
