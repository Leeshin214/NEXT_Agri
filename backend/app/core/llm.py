"""
LLM 클라이언트 헬퍼 — 백엔드의 모든 OpenAI 호출은 이 모듈을 통해 만든다.

이후 LLM 키/모델 정책은 여기서만 바꾸도록 한다.
다른 모듈에서 AsyncOpenAI/openai.OpenAI 를 직접 인스턴스화하지 않는다.
"""

from __future__ import annotations

import openai
from openai import AsyncOpenAI

from app.core.config import settings


# 전 백엔드 공통 기본 모델
DEFAULT_MODEL: str = "gpt-4o-mini"


# 모듈 레벨 싱글톤 — lazy 생성
# AsyncOpenAI 는 인스턴스화 자체는 이벤트 루프에 묶이지 않지만,
# 내부 httpx.AsyncClient 가 첫 사용 시점의 루프에 바인딩되므로
# import 시점이 아닌 첫 호출 시점에 만든다.
_async_client: AsyncOpenAI | None = None
_sync_client: openai.OpenAI | None = None


def get_openai_client() -> AsyncOpenAI:
    """비동기 OpenAI 클라이언트 싱글톤."""
    global _async_client
    if _async_client is None:
        _async_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _async_client


def get_openai_sync_client() -> openai.OpenAI:
    """동기 OpenAI 클라이언트 싱글톤. 동기 컨텍스트(예: asyncio.to_thread 안)에서 사용."""
    global _sync_client
    if _sync_client is None:
        _sync_client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
    return _sync_client
