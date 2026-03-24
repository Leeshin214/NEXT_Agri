import json
from typing import Any

import httpx
import jwt
from fastapi import HTTPException, status
from jwt.algorithms import ECAlgorithm

from app.core.config import settings

_jwks_cache: dict | None = None


async def _get_supabase_public_key(kid: str | None) -> Any:
    global _jwks_cache
    if _jwks_cache is None:
        jwks_url = f"{settings.SUPABASE_URL}/auth/v1/.well-known/jwks.json"
        async with httpx.AsyncClient() as client:
            resp = await client.get(jwks_url, timeout=5.0)
            resp.raise_for_status()
            _jwks_cache = resp.json()

    keys = _jwks_cache.get("keys", [])
    key_data = next((k for k in keys if k.get("kid") == kid), None)
    if key_data is None and keys:
        key_data = keys[0]
    if key_data is None:
        raise HTTPException(status_code=401, detail="JWKS: no matching key")

    return ECAlgorithm.from_jwk(json.dumps(key_data))


async def verify_supabase_jwt(token: str) -> dict:
    """Supabase JWT 토큰 검증 및 payload 반환"""
    try:
        header = jwt.get_unverified_header(token)
        alg = header.get("alg", "")

        if alg == "ES256":
            public_key = await _get_supabase_public_key(header.get("kid"))
            payload = jwt.decode(
                token,
                public_key,
                algorithms=["ES256"],
                audience="authenticated",
                options={"verify_exp": True},
            )
        else:
            payload = jwt.decode(
                token,
                settings.SUPABASE_JWT_SECRET,
                algorithms=["HS256", "HS512"],
                audience="authenticated",
                options={"verify_exp": True},
            )

        return payload

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except HTTPException:
        raise
    except jwt.InvalidTokenError as e:
        print(f"[AUTH] JWT 검증 실패: {str(e)}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {str(e)}")
