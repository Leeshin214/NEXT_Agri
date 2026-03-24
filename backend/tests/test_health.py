import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    """헬스체크 엔드포인트 테스트"""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
