import pytest
from unittest.mock import MagicMock
from httpx import AsyncClient


SAMPLE_ROOM = {
    "id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
    "seller_id": "11111111-1111-1111-1111-111111111111",
    "buyer_id": "22222222-2222-2222-2222-222222222222",
    "order_id": None,
    "last_message": "안녕하세요",
    "last_message_at": "2026-03-21T10:00:00",
    "created_at": "2026-03-21T00:00:00",
    "updated_at": "2026-03-21T10:00:00",
}

SAMPLE_MESSAGE = {
    "id": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
    "room_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
    "sender_id": "11111111-1111-1111-1111-111111111111",
    "content": "사과 10박스 견적 부탁드립니다",
    "is_read": False,
    "created_at": "2026-03-21T10:00:00",
}


@pytest.mark.asyncio
async def test_list_chat_rooms(client: AsyncClient, mock_seller_auth, mock_supabase):
    """채팅방 목록 조회"""
    table = mock_supabase.table("chat_rooms")
    execute_result = MagicMock()
    execute_result.data = [SAMPLE_ROOM]
    table.execute.return_value = execute_result

    users_table = mock_supabase.table("users")
    user_result = MagicMock()
    user_result.data = {"name": "테스트구매자", "company_name": "테스트마트"}
    users_table.execute.return_value = user_result

    messages_table = mock_supabase.table("messages")
    msg_result = MagicMock()
    msg_result.data = []
    msg_result.count = 0
    messages_table.execute.return_value = msg_result

    response = await client.get("/api/v1/chat/rooms")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_send_message(client: AsyncClient, mock_seller_auth, mock_supabase):
    """메시지 전송"""
    room_id = "dddddddd-dddd-dddd-dddd-dddddddddddd"

    table = mock_supabase.table("messages")
    execute_result = MagicMock()
    execute_result.data = [SAMPLE_MESSAGE]
    table.execute.return_value = execute_result

    rooms_table = mock_supabase.table("chat_rooms")
    rooms_result = MagicMock()
    rooms_result.data = [SAMPLE_ROOM]
    rooms_table.execute.return_value = rooms_result

    response = await client.post(
        f"/api/v1/chat/rooms/{room_id}/messages",
        json={"content": "사과 10박스 견적 부탁드립니다"},
    )
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_mark_as_read(client: AsyncClient, mock_seller_auth, mock_supabase):
    """읽음 처리"""
    room_id = "dddddddd-dddd-dddd-dddd-dddddddddddd"
    response = await client.post(f"/api/v1/chat/rooms/{room_id}/read")
    assert response.status_code == 204
