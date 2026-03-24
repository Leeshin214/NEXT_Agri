# SKILL_AI.md — AI Assistant Agent

> **마지막 동기화**: 2026-03-22 | 실제 코드 기준으로 작성됨

## 역할
Anthropic Claude API를 활용한 AI 업무 도우미 기능을 구현한다.  
판매자/구매자 각각의 업무 맥락에 맞는 AI 응답을 스트리밍으로 제공한다.

---

## AI 기능 목록

| 기능 | 엔드포인트 | 설명 |
|------|-----------|------|
| 일반 대화 | POST /ai/chat | 프롬프트 자유 입력, 스트리밍 응답 |
| 업무 요약 | POST /ai/daily-summary | 오늘의 업무 자동 요약 |
| 채팅 요약 | POST /ai/summarize-chat | 채팅 내용 요약 |
| 메시지 초안 | POST /ai/draft-message | 상황에 맞는 메시지 초안 작성 |
| 재고 분석 | POST /ai/inventory-alert | 재고 현황 분석 및 경고 |

---

## System Prompt 설계

### 판매자 System Prompt
```python
SELLER_SYSTEM_PROMPT = """당신은 AgriFlow 농산물 유통 플랫폼의 AI 업무 도우미입니다.

[사용자 정보]
- 역할: 판매자 (농가/도매상/유통업체)
- 회사명: {company_name}
- 담당자: {user_name}

[현재 업무 현황]
{context}

[응답 원칙]
1. 반드시 한국어로 답변
2. 농산물 유통업 실무 용어 사용 (출하, 납품, 단가, 도매가, 박스 등)
3. 간결하고 실용적인 정보 제공
4. 수치가 있으면 구체적으로 언급
5. 긴 답변은 항목으로 구분하여 읽기 쉽게 작성
6. 불확실한 정보는 확인이 필요하다고 명시"""

### 구매자 System Prompt
BUYER_SYSTEM_PROMPT = """당신은 AgriFlow 농산물 유통 플랫폼의 AI 업무 도우미입니다.

[사용자 정보]
- 역할: 구매자 (마트/식자재업체/식당)
- 회사명: {company_name}
- 담당자: {user_name}

[현재 업무 현황]
{context}

[응답 원칙]
1. 반드시 한국어로 답변
2. 구매자 관점의 용어 사용 (발주, 납품, 단가 비교, 수급 등)
3. 비용 절감 및 효율적인 구매에 도움되는 정보 우선
4. 간결하고 실용적인 정보 제공
5. 납품 일정, 가격 변동에 민감하게 반응"""
```

---

## Backend 구현

### 컨텍스트 빌더 (사용자별 현황 정보 수집)
```python
# app/services/ai_context.py
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import User, Order, Product, CalendarEvent

async def build_seller_context(user: User, db: AsyncSession) -> str:
    """판매자 컨텍스트: 오늘 출하, 재고, 미응답 견적"""
    from datetime import date

    # 오늘 출하 일정
    today_shipments = await db.execute(
        select(CalendarEvent)
        .where(
            CalendarEvent.user_id == user.id,
            CalendarEvent.event_type == 'SHIPMENT',
            CalendarEvent.event_date == date.today()
        )
    )
    shipments = today_shipments.scalars().all()

    # 재고 부족 품목
    low_stock = await db.execute(
        select(Product)
        .where(
            Product.seller_id == user.id,
            Product.status.in_(['LOW_STOCK', 'OUT_OF_STOCK']),
            Product.deleted_at.is_(None)
        )
    )
    low_items = low_stock.scalars().all()

    # 미응답 견적
    pending_orders = await db.execute(
        select(func.count(Order.id))
        .where(
            Order.seller_id == user.id,
            Order.status == 'QUOTE_REQUESTED'
        )
    )
    pending_count = pending_orders.scalar()

    context = f"""
오늘 출하 예정: {len(shipments)}건
{chr(10).join([f'- {s.title}' for s in shipments]) if shipments else '- 없음'}

재고 부족 품목: {len(low_items)}개
{chr(10).join([f'- {p.name}: {p.stock_quantity}{p.unit} ({p.status})' for p in low_items]) if low_items else '- 없음'}

미응답 견적 요청: {pending_count}건
"""
    return context

async def build_buyer_context(user: User, db: AsyncSession) -> str:
    """구매자 컨텍스트: 진행중 주문, 오늘 납품, 대기 견적"""
    from datetime import date

    # 진행중 주문
    active_orders = await db.execute(
        select(func.count(Order.id))
        .where(
            Order.buyer_id == user.id,
            Order.status.in_(['CONFIRMED', 'PREPARING', 'SHIPPING'])
        )
    )

    # 오늘 납품 예정
    today_deliveries = await db.execute(
        select(CalendarEvent)
        .where(
            CalendarEvent.user_id == user.id,
            CalendarEvent.event_type == 'DELIVERY',
            CalendarEvent.event_date == date.today()
        )
    )
    deliveries = today_deliveries.scalars().all()

    context = f"""
진행중 주문: {active_orders.scalar()}건
오늘 납품 예정: {len(deliveries)}건
{chr(10).join([f'- {d.title}' for d in deliveries]) if deliveries else '- 없음'}
"""
    return context
```

### AI 엔드포인트 (스트리밍)
```python
# app/api/v1/ai_assistant.py
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from anthropic import AsyncAnthropic
from pydantic import BaseModel
from app.dependencies import get_current_user, get_db

router = APIRouter(prefix="/ai", tags=["ai"])
client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

class AIChatRequest(BaseModel):
    prompt: str
    prompt_type: Optional[str] = None  # 빠른 프롬프트 유형

@router.post("/chat")
async def ai_chat(
    request: AIChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """스트리밍 AI 응답"""
    # 컨텍스트 빌드
    if current_user.role == 'SELLER':
        context = await build_seller_context(current_user, db)
        system = SELLER_SYSTEM_PROMPT.format(
            company_name=current_user.company_name or '미설정',
            user_name=current_user.name,
            context=context
        )
    else:
        context = await build_buyer_context(current_user, db)
        system = BUYER_SYSTEM_PROMPT.format(
            company_name=current_user.company_name or '미설정',
            user_name=current_user.name,
            context=context
        )

    async def generate():
        async with client.messages.stream(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": request.prompt}]
        ) as stream:
            async for text in stream.text_stream:
                yield f"data: {text}\n\n"
        yield "data: [DONE]\n\n"

        # 대화 기록 저장 (비동기)
        final_response = await stream.get_final_text()
        await save_ai_conversation(current_user.id, request.prompt, final_response, request.prompt_type, db)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
```

---

## Frontend 구현

### AI 스트리밍 훅
```typescript
// frontend/hooks/useAIStream.ts
import { useState, useCallback, useRef } from 'react';
import { createClient } from '@/lib/supabase/client';

export function useAIStream() {
  const [response, setResponse] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const stream = useCallback(async (prompt: string, promptType?: string) => {
    if (!prompt.trim() || isStreaming) return;

    setResponse('');
    setIsStreaming(true);

    try {
      abortRef.current = new AbortController();
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

      const supabase = createClient();
      const { data } = await supabase.auth.getSession();
      const token = data.session?.access_token;

      const res = await fetch(`${apiUrl}/api/v1/ai/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ prompt, prompt_type: promptType }),
        signal: abortRef.current.signal,
      });

      const reader = res.body?.getReader();
      if (!reader) return;

      const decoder = new TextDecoder();
      let accumulated = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        for (const line of chunk.split('\n')) {
          if (line.startsWith('data: ')) {
            const text = line.slice(6);
            if (text === '[DONE]') break;
            accumulated += text;
            setResponse(accumulated);
          }
        }
      }
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        setResponse('AI 응답을 받는 중 오류가 발생했습니다. 다시 시도해주세요.');
      }
    } finally {
      setIsStreaming(false);
    }
  }, [isStreaming]);

  const abort = useCallback(() => { abortRef.current?.abort(); }, []);
  const reset = useCallback(() => { setResponse(''); }, []);

  return { response, isStreaming, stream, abort, reset };
}
```

### 빠른 프롬프트 설정
```typescript
// src/constants/aiPrompts.ts
export const sellerQuickPrompts = [
  {
    label: '오늘 출하 일정 요약',
    prompt: '오늘 출하 예정인 일정을 모두 요약해줘. 품목, 수량, 거래처를 포함해서 알려줘.',
    icon: '📦',
    type: 'SHIPMENT_SUMMARY'
  },
  {
    label: '미응답 견적 정리',
    prompt: '현재 미응답 상태인 견적 요청을 정리해줘. 우선순위와 함께 알려줘.',
    icon: '📋',
    type: 'PENDING_QUOTES'
  },
  {
    label: '재고 부족 품목 확인',
    prompt: '재고가 부족하거나 소진된 품목을 알려주고, 보충이 필요한 수량을 추천해줘.',
    icon: '⚠️',
    type: 'INVENTORY_ALERT'
  },
  {
    label: '구매자 답장 초안 작성',
    prompt: '가장 최근 견적 요청에 대한 정중하고 전문적인 답변 초안을 작성해줘.',
    icon: '✉️',
    type: 'DRAFT_REPLY'
  },
];

export const buyerQuickPrompts = [
  {
    label: '이번 주 납품 일정 정리',
    prompt: '이번 주 납품 예정인 일정을 모두 정리해줘. 공급처와 품목을 포함해서 알려줘.',
    icon: '🚚',
    type: 'DELIVERY_SUMMARY'
  },
  {
    label: '단가 비교 요약',
    prompt: '현재 거래 중인 품목들의 단가를 공급처별로 비교 요약해줘.',
    icon: '💰',
    type: 'PRICE_COMPARISON'
  },
  {
    label: '판매자 문의 메시지 초안',
    prompt: '신규 품목 견적을 요청하는 정중한 문의 메시지 초안을 작성해줘.',
    icon: '✉️',
    type: 'DRAFT_INQUIRY'
  },
  {
    label: '지연 가능 주문 확인',
    prompt: '납품 지연 가능성이 있는 주문을 알려주고, 대응 방법을 추천해줘.',
    icon: '🔔',
    type: 'DELAY_RISK'
  },
];
```

### AI 채팅 패널 컴포넌트 (실제 구현)
```tsx
// frontend/components/layout/AIChatPanel.tsx
// AppLayout에 우측 고정으로 삽입됨 — 별도 라우트/페이지 없음
// w-1/2 고정, border-l로 main 영역과 구분
// react-markdown 미사용 — whitespace-pre-wrap으로 텍스트 직접 렌더링

export default function AIChatPanel() {
  const [input, setInput] = useState('');
  const { response, isStreaming, stream } = useAIStream();
  const { user } = useAuthStore();

  const quickPrompts = user?.role === 'SELLER' ? sellerQuickPrompts : buyerQuickPrompts;

  // 빠른 프롬프트: Sparkles 아이콘 + label 텍스트, rounded-full pill 스타일
  // 응답 영역: whitespace-pre-wrap, 스트리밍 중 커서 블링크 (animate-pulse)
  // 입력창: Enter 전송, Shift+Enter 줄바꿈, isStreaming 중 disabled
  // 전송 버튼: Send 아이콘 (w-9 h-9 정사각형)
}
```

> **주의**: `AIResponsePanel.tsx`는 존재하지 않음. 실제 컴포넌트는 `AIChatPanel.tsx` (layout 폴더).

---

## 작업 체크리스트

- [ ] Anthropic SDK 설치 (`pip install anthropic`)
- [ ] System Prompt 판매자/구매자 분리 작성
- [ ] 컨텍스트 빌더 (seller/buyer 각각)
- [ ] AI 스트리밍 엔드포인트
- [ ] 채팅 요약 엔드포인트
- [ ] ai_conversations 저장 로직
- [x] useAIStream 훅 (SSE 파싱, AbortController, abort/reset 포함)
- [x] aiPrompts 상수 (판매자/구매자 각 4개)
- [x] AIChatPanel 컴포넌트 (AppLayout 우측 고정 패널)
- [ ] 에러 처리 (API 키 오류, Rate Limit 등)

---

## 실전 발견 사항

> **agent 전용 기록 공간**: 실제로 더 나은 AI 응답을 만들어낸 패턴만 기록한다.
> 이론적인 프롬프트 엔지니어링 팁은 추가하지 않는다.

### 검증된 프롬프트 패턴

_작업을 진행하면서 채워진다._

### 주의사항 & 함정

_작업을 진행하면서 채워진다._
