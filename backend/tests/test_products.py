import pytest
from unittest.mock import patch, MagicMock
from httpx import AsyncClient


SAMPLE_PRODUCT = {
    "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    "seller_id": "11111111-1111-1111-1111-111111111111",
    "name": "사과",
    "category": "FRUIT",
    "origin": "경북 청송",
    "spec": None,
    "unit": "box",
    "price_per_unit": 45000,
    "stock_quantity": 100,
    "min_order_qty": 1,
    "status": "NORMAL",
    "image_url": None,
    "description": None,
    "deleted_at": None,
    "created_at": "2026-03-21T00:00:00",
    "updated_at": "2026-03-21T00:00:00",
}


@pytest.mark.asyncio
async def test_list_products(client: AsyncClient, mock_seller_auth, mock_supabase):
    """상품 목록 조회"""
    # 모킹된 Supabase 응답 설정
    table = mock_supabase.table("products")
    execute_result = MagicMock()
    execute_result.data = [SAMPLE_PRODUCT]
    execute_result.count = 1
    table.execute.return_value = execute_result

    response = await client.get("/api/v1/products")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_create_product_as_seller(client: AsyncClient, mock_seller_auth, mock_supabase):
    """판매자 상품 등록"""
    table = mock_supabase.table("products")
    execute_result = MagicMock()
    execute_result.data = [SAMPLE_PRODUCT]
    table.execute.return_value = execute_result

    response = await client.post(
        "/api/v1/products",
        json={
            "name": "사과",
            "category": "FRUIT",
            "origin": "경북 청송",
            "unit": "box",
            "price_per_unit": 45000,
            "stock_quantity": 100,
        },
    )
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_create_product_as_buyer_forbidden(client: AsyncClient, mock_buyer_auth, mock_supabase):
    """구매자는 상품 등록 불가"""
    response = await client.post(
        "/api/v1/products",
        json={
            "name": "사과",
            "category": "FRUIT",
            "unit": "box",
            "price_per_unit": 45000,
            "stock_quantity": 100,
        },
    )
    assert response.status_code == 403
