import time

import jwt
import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from httpx import AsyncClient

from app.core.security import verify_supabase_jwt


# ─── JWT 검증 테스트 ───

JWT_SECRET = "test-jwt-secret"


@pytest.fixture(autouse=True)
def mock_settings():
    with patch("app.core.security.settings") as mock:
        mock.SUPABASE_JWT_SECRET = JWT_SECRET
        yield mock


def make_token(payload: dict, secret: str = JWT_SECRET, algorithm: str = "HS256") -> str:
    return jwt.encode(payload, secret, algorithm=algorithm)


async def test_valid_token():
    """유효한 JWT 토큰 검증 성공"""
    payload = {
        "sub": "user-123",
        "aud": "authenticated",
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
    }
    token = make_token(payload)
    result = await verify_supabase_jwt(token)
    assert result["sub"] == "user-123"


async def test_expired_token():
    """만료된 JWT 토큰은 401 에러"""
    payload = {
        "sub": "user-123",
        "aud": "authenticated",
        "exp": int(time.time()) - 3600,
        "iat": int(time.time()) - 7200,
    }
    token = make_token(payload)
    with pytest.raises(HTTPException) as exc_info:
        await verify_supabase_jwt(token)
    assert exc_info.value.status_code == 401
    assert "expired" in exc_info.value.detail.lower()


async def test_invalid_token():
    """잘못된 토큰은 401 에러"""
    with pytest.raises(HTTPException) as exc_info:
        await verify_supabase_jwt("not-a-valid-token")
    assert exc_info.value.status_code == 401


async def test_wrong_secret():
    """시크릿이 다른 토큰은 401 에러"""
    payload = {
        "sub": "user-123",
        "aud": "authenticated",
        "exp": int(time.time()) + 3600,
    }
    token = make_token(payload, secret="wrong-secret")
    with pytest.raises(HTTPException) as exc_info:
        await verify_supabase_jwt(token)
    assert exc_info.value.status_code == 401


async def test_wrong_audience():
    """audience가 다른 토큰은 401 에러"""
    payload = {
        "sub": "user-123",
        "aud": "wrong-audience",
        "exp": int(time.time()) + 3600,
    }
    token = make_token(payload)
    with pytest.raises(HTTPException) as exc_info:
        await verify_supabase_jwt(token)
    assert exc_info.value.status_code == 401


# ─── 역할 기반 접근 제어 테스트 ───

@pytest.mark.asyncio
async def test_seller_can_access_products(client: AsyncClient, mock_seller_auth, mock_supabase):
    """판매자는 상품 엔드포인트에 접근 가능"""
    table = mock_supabase.table("products")
    execute_result = MagicMock()
    execute_result.data = []
    execute_result.count = 0
    table.execute.return_value = execute_result

    response = await client.get("/api/v1/products")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_buyer_cannot_create_product(client: AsyncClient, mock_buyer_auth, mock_supabase):
    """구매자는 상품 생성 불가 (403)"""
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


@pytest.mark.asyncio
async def test_unauthenticated_request(client: AsyncClient):
    """인증되지 않은 요청은 401/403 에러"""
    response = await client.get("/api/v1/users/me")
    assert response.status_code in [401, 403]


@pytest.mark.asyncio
async def test_health_does_not_require_auth(client: AsyncClient):
    """헬스체크는 인증 불필요"""
    response = await client.get("/health")
    assert response.status_code == 200
