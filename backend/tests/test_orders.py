import pytest
from unittest.mock import MagicMock
from httpx import AsyncClient


SAMPLE_ORDER = {
    "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    "order_number": "ORD-20260321-001",
    "buyer_id": "22222222-2222-2222-2222-222222222222",
    "seller_id": "11111111-1111-1111-1111-111111111111",
    "status": "QUOTE_REQUESTED",
    "total_amount": 450000,
    "delivery_date": "2026-03-25",
    "delivery_address": "서울시 강남구",
    "notes": None,
    "created_at": "2026-03-21T00:00:00",
    "updated_at": "2026-03-21T00:00:00",
    "items": [],
}


@pytest.mark.asyncio
async def test_list_orders_as_seller(client: AsyncClient, mock_seller_auth, mock_supabase):
    """판매자 주문 목록 조회"""
    table = mock_supabase.table("orders")
    execute_result = MagicMock()
    execute_result.data = [SAMPLE_ORDER]
    execute_result.count = 1
    table.execute.return_value = execute_result

    response = await client.get("/api/v1/orders")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_list_orders_as_buyer(client: AsyncClient, mock_buyer_auth, mock_supabase):
    """구매자 주문 목록 조회"""
    table = mock_supabase.table("orders")
    execute_result = MagicMock()
    execute_result.data = [SAMPLE_ORDER]
    execute_result.count = 1
    table.execute.return_value = execute_result

    response = await client.get("/api/v1/orders")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_create_order_as_buyer(client: AsyncClient, mock_buyer_auth, mock_supabase):
    """구매자 주문 생성"""
    table = mock_supabase.table("orders")
    # insert().execute() 는 list 반환
    execute_result = MagicMock()
    execute_result.data = [SAMPLE_ORDER]
    table.execute.return_value = execute_result

    # get_order 내부의 .single().execute() 는 dict 반환
    single_execute_result = MagicMock()
    single_execute_result.data = SAMPLE_ORDER
    table.single.return_value.execute.return_value = single_execute_result

    items_table = mock_supabase.table("order_items")
    items_result = MagicMock()
    items_result.data = []
    items_table.execute.return_value = items_result

    response = await client.post(
        "/api/v1/orders",
        json={
            "seller_id": "11111111-1111-1111-1111-111111111111",
            "delivery_date": "2026-03-25",
            "delivery_address": "서울시 강남구",
            "items": [
                {"product_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "quantity": 10, "unit_price": 45000}
            ],
        },
    )
    assert response.status_code in [200, 201]
