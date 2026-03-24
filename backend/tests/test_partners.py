import pytest
from unittest.mock import MagicMock
from httpx import AsyncClient


SAMPLE_PARTNER = {
    "id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
    "user_id": "11111111-1111-1111-1111-111111111111",
    "partner_user_id": "22222222-2222-2222-2222-222222222222",
    "status": "ACTIVE",
    "is_favorite": False,
    "notes": None,
    "partner_name": "테스트구매자",
    "partner_company": "테스트마트",
    "partner_phone": "010-9876-5432",
    "created_at": "2026-03-21T00:00:00",
    "updated_at": "2026-03-21T00:00:00",
}


@pytest.mark.asyncio
async def test_list_partners(client: AsyncClient, mock_seller_auth, mock_supabase):
    """거래처 목록 조회"""
    table = mock_supabase.table("partners")
    execute_result = MagicMock()
    execute_result.data = [SAMPLE_PARTNER]
    execute_result.count = 1
    table.execute.return_value = execute_result

    response = await client.get("/api/v1/partners")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_create_partner(client: AsyncClient, mock_seller_auth, mock_supabase):
    """거래처 등록"""
    table = mock_supabase.table("partners")
    execute_result = MagicMock()
    execute_result.data = [SAMPLE_PARTNER]
    table.execute.return_value = execute_result

    users_table = mock_supabase.table("users")
    user_result = MagicMock()
    user_result.data = {
        "name": "테스트구매자",
        "company_name": "테스트마트",
        "phone": "010-9876-5432",
    }
    users_table.execute.return_value = user_result

    response = await client.post(
        "/api/v1/partners",
        json={"partner_user_id": "22222222-2222-2222-2222-222222222222"},
    )
    assert response.status_code == 201
