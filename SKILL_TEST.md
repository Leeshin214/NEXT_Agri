# SKILL_TEST.md — Testing Agent

## 역할
프론트엔드(Vitest + Testing Library)와 백엔드(pytest + pytest-asyncio) 테스트를 작성한다.

---

## Backend 테스트 (pytest)

### 설정
```python
# tests/conftest.py
import pytest
import asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from app.main import app
from app.core.config import settings

TEST_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost/agriflow_test"

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as ac:
        yield ac

@pytest.fixture
async def seller_token(client):
    """판매자 테스트 토큰 생성"""
    # Supabase Auth 모킹 또는 테스트 토큰 사용
    ...

@pytest.fixture
async def buyer_token(client):
    """구매자 테스트 토큰 생성"""
    ...
```

### API 테스트 예시
```python
# tests/test_products.py
import pytest

@pytest.mark.asyncio
async def test_create_product_as_seller(client, seller_token):
    response = await client.post(
        "/api/v1/products",
        json={
            "name": "사과",
            "category": "FRUIT",
            "origin": "경북 청송",
            "unit": "box",
            "price_per_unit": 45000,
            "stock_quantity": 100
        },
        headers={"Authorization": f"Bearer {seller_token}"}
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["name"] == "사과"
    assert data["status"] == "NORMAL"

@pytest.mark.asyncio
async def test_create_product_as_buyer_forbidden(client, buyer_token):
    """구매자는 상품 등록 불가"""
    response = await client.post(
        "/api/v1/products",
        json={"name": "사과", "category": "FRUIT", "unit": "box", "price_per_unit": 45000},
        headers={"Authorization": f"Bearer {buyer_token}"}
    )
    assert response.status_code == 403

@pytest.mark.asyncio
async def test_list_products_public(client):
    """비로그인도 상품 목록 조회 가능 (공개 탐색)"""
    response = await client.get("/api/v1/products")
    assert response.status_code == 200

@pytest.mark.asyncio
async def test_order_status_flow(client, seller_token, buyer_token):
    """주문 상태 플로우 테스트"""
    # 1. 구매자 견적 요청
    order_res = await client.post(
        "/api/v1/orders",
        json={"seller_id": "...", "items": [...]},
        headers={"Authorization": f"Bearer {buyer_token}"}
    )
    order_id = order_res.json()["data"]["id"]
    assert order_res.json()["data"]["status"] == "QUOTE_REQUESTED"

    # 2. 판매자 견적 확정
    confirm_res = await client.patch(
        f"/api/v1/orders/{order_id}/status",
        json={"status": "CONFIRMED"},
        headers={"Authorization": f"Bearer {seller_token}"}
    )
    assert confirm_res.json()["data"]["status"] == "CONFIRMED"
```

---

## Frontend 테스트 (Vitest + Testing Library)

### 설정
```typescript
// vitest.config.ts
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: true,
  },
});
```

```typescript
// src/test/setup.ts
import '@testing-library/jest-dom';
import { vi } from 'vitest';

// Supabase mock
vi.mock('@/lib/supabase/client', () => ({
  createClient: () => ({
    auth: {
      getSession: vi.fn().mockResolvedValue({ data: { session: null } }),
      onAuthStateChange: vi.fn().mockReturnValue({ data: { subscription: { unsubscribe: vi.fn() } } }),
    },
    channel: vi.fn().mockReturnValue({
      on: vi.fn().mockReturnThis(),
      subscribe: vi.fn(),
    }),
    removeChannel: vi.fn(),
  }),
}));
```

### 컴포넌트 테스트 예시
```typescript
// src/components/common/__tests__/StatusBadge.test.tsx
import { render, screen } from '@testing-library/react';
import StatusBadge from '../StatusBadge';

describe('StatusBadge', () => {
  it('NORMAL 상태를 올바르게 표시한다', () => {
    render(<StatusBadge status="NORMAL" />);
    expect(screen.getByText('정상')).toBeInTheDocument();
  });

  it('LOW_STOCK 상태에 경고 스타일이 적용된다', () => {
    const { container } = render(<StatusBadge status="LOW_STOCK" />);
    expect(container.firstChild).toHaveClass('bg-yellow-100');
  });
});

// src/hooks/__tests__/useAIStream.test.ts
import { renderHook, act } from '@testing-library/react';
import { useAIStream } from '../useAIStream';

describe('useAIStream', () => {
  it('스트리밍 중 isStreaming이 true가 된다', async () => {
    const { result } = renderHook(() => useAIStream());
    
    global.fetch = vi.fn().mockResolvedValue({
      body: new ReadableStream({
        start(controller) {
          controller.enqueue(new TextEncoder().encode('data: 안녕\n\n'));
          controller.enqueue(new TextEncoder().encode('data: [DONE]\n\n'));
          controller.close();
        },
      }),
    });

    act(() => { result.current.stream('테스트 프롬프트'); });
    expect(result.current.isStreaming).toBe(true);
  });
});
```

---

## 테스트 실행 명령

```bash
# Backend
cd backend
pytest tests/ -v --asyncio-mode=auto

# Frontend
cd frontend
npm run test
npm run test:coverage
```

---

## 작업 체크리스트

- [ ] pytest conftest.py (DB 픽스처, 인증 픽스처)
- [ ] API 테스트: products, orders, partners, chat
- [ ] 권한 테스트: 역할별 접근 제어
- [ ] Vitest 설정
- [ ] 공통 컴포넌트 단위 테스트
- [ ] 훅 테스트 (useAIStream, useChat)
- [ ] CI 파이프라인 (GitHub Actions)
