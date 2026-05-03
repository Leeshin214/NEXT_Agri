# SKILL_AI.md — AI Assistant Agent

> **마지막 동기화**: 2026-04-29 | 실제 코드 기준으로 작성됨 (OpenAI 통일 후)

## 역할
OpenAI API 를 활용한 AI 업무 도우미 기능을 구현한다.
판매자/구매자 각각의 업무 맥락에 맞는 AI 응답을 스트리밍으로 제공한다.

---

## AI 기능 목록

| 기능 | 엔드포인트 / 위치 | 설명 |
|------|-----------|------|
| 일반 대화 | POST /ai/chat | 프롬프트 자유 입력, 스트리밍 응답 |
| 채팅 요약 | POST /ai/summarize-chat | 채팅 내용 요약 |
| 메시지 초안 | POST /ai/draft-message | 상황에 맞는 메시지 초안 작성 |
| 재고 분석 | POST /ai/inventory-alert | 재고 현황 분석 및 경고 |
| 채팅 합의 감지 | agent_tools.analyze_chat_consensus | 채팅 메시지 → 합의/협상/거절/일반 분류, 합의 시 주문·캘린더 자동 생성 (AgenticPay) |
| 메인 오케스트레이터 | POST /ai/agent/chat | tool_use 기반 — DB 조회/수정 도구 자체 선택 |

---

## LLM 클라이언트 헬퍼 (필수 사용)

백엔드의 모든 OpenAI 호출은 `app/core/llm.py` 의 헬퍼를 통해 만든다.
다른 모듈에서 `AsyncOpenAI` / `openai.OpenAI` 를 직접 인스턴스화하지 않는다.

```python
# app/core/llm.py 사용 예시
from app.core.llm import get_openai_client, get_openai_sync_client, DEFAULT_MODEL

# 비동기 컨텍스트 (FastAPI 라우터 등)
client = get_openai_client()  # AsyncOpenAI 싱글톤

# 동기 컨텍스트 (asyncio.to_thread 안에서 호출 시)
sync_client = get_openai_sync_client()  # openai.OpenAI 싱글톤
```

- 싱글톤은 lazy 초기화 (첫 호출 시점에 생성) — `AsyncOpenAI` 의 내부 httpx 클라이언트가 첫 사용 시점의 이벤트 루프에 바인딩되기 때문.
- 모델은 `DEFAULT_MODEL = "gpt-4o-mini"` 사용.

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
from pydantic import BaseModel
from app.core.llm import get_openai_client, DEFAULT_MODEL
from app.dependencies import get_current_user, get_db

router = APIRouter(prefix="/ai", tags=["ai"])

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

    client = get_openai_client()
    accumulated = []  # 대화 기록 저장용

    async def generate():
        # OpenAI: system 은 messages 배열의 첫 항목으로 넣음
        stream = await client.chat.completions.create(
            model=DEFAULT_MODEL,
            max_tokens=1024,
            stream=True,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": request.prompt},
            ],
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                accumulated.append(delta)
                yield f"data: {delta}\n\n"
        yield "data: [DONE]\n\n"

        # 대화 기록 저장
        final_response = "".join(accumulated)
        await save_ai_conversation(
            current_user.id, request.prompt, final_response,
            request.prompt_type, db,
        )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
```

> **응답 파싱 핵심**:
> - 비스트리밍: `response.choices[0].message.content`
> - 스트리밍: `chunk.choices[0].delta.content` (None 일 수 있으니 falsy 체크)
> - `system` 은 별도 인자가 아니라 `messages` 배열의 첫 항목 (`role: "system"`)으로 넣는다.

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

- [ ] OpenAI SDK 설치 (`pip install openai`)
- [ ] `app/core/llm.py` 헬퍼 사용 (직접 `AsyncOpenAI` 인스턴스화 금지)
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

#### 채팅창 가독성 — 마크다운 강조 절대 금지 (2026-05-03 추가)
- AgriFlow AI 응답은 `frontend/components/chat/MessageBubble.tsx` 에서 **마크다운 렌더러 없이 순수 텍스트로** 표시됨 → `**굵게**` / `*기울임*` 같은 표기가 별표 그대로 노출되어 사용자 가독성을 해친다.
- GPT-4o-mini 는 한국어 응답에서 디폴트로 마크다운 강조를 매우 자주 쓰므로, **시스템 프롬프트에 명시적으로 금지하지 않으면 무조건 별표가 들어간다.**
- 적용한 위치 (orchestrator.py):
  - `AGENT_BASE_SYSTEM` [핵심 대화 원칙] 7번 — SELLER/BUYER 양쪽 + response_node 까지 한 곳에서 커버 (가장 강력)
  - `calendar_data_node` system_prompt — `(가독성)` 항목으로 한 줄 추가
  - `calendar_reason_node` system_prompt — 추천 일정 자연어화 시점에서 한 줄 추가
  - `response_node` 의 user 프롬프트 — tool 결과 요약 시 `JSON/코드 블록 금지` 옆에 마크다운 강조 금지도 같이 명시
- 핵심 문구 패턴: "응답은 마크다운이 렌더링되지 않는 채팅창에 그대로 노출됩니다. `**굵게**`, `*기울임*` 같은 마크다운 강조와 표(`|`), 코드 블록(```), 헤더(`#`)는 절대 사용하지 마세요." → "왜 안 되는지(별표가 글자로 보임)" 함께 설명하면 LLM 준수율이 더 높음.
- 표·코드블록·헤더도 같은 이유로 함께 금지 (한 번에 묶어서 끝).
- 이모지는 사용자가 명시적으로 요청하지 않는 한 본문 사용 금지를 명시.
- 이 가이드는 한 번 BASE 에 박아두면 SELLER 합성본·BUYER 합성본·response_node 요약까지 자동 적용된다 (`AGENT_SELLER_SYSTEM`/`AGENT_BUYER_SYSTEM` 가 BASE 를 합성하기 때문).
- 주의: `inventory_order_node` 의 `final_text.replace("**", "")` 같은 후처리는 부분적으로만 동작 (오타 변수명 `fianl_text` 도 잔존) → 프롬프트 차원에서 막는 것이 정확함.

#### TEA 방식 오케스트레이터 (orchestrator.py 실제 구조)
```
orchestrator_node (tools 없음, response_format=json_object)
    → intent: INVENTORY / ORDER → inventory_order_node
    → intent: GENERAL → response_node (직접 답변 포함)

inventory_order_node (자체 LLM + TOOLS + 자체 루프 최대 3회)
    → tool 선택·실행·추가 tool 여부 판단 모두 자체 처리
    → 완료 후 response_node

response_node
    → success=True 이고 재고 부족 아닌 경우: tool_results[-1].message 있으면 LLM 없이 바로 반환
    → success=False 또는 재고 부족(LOW_STOCK/OUT_OF_STOCK/요청수량>재고): 단락회로 건너뜀, LLM이 타협안 생성
    → 그 외(message 없음): LLM으로 요약
```

#### orchestrator_node 핵심 패턴
- `response_format={"type": "json_object"}` 강제 → `{"intent": "INVENTORY"}` 형식
- tools 파라미터 완전 제거 (tool_choice도 없음)
- GENERAL인 경우 `{"intent": "GENERAL", "response": "답변"}` 형식으로 직접 답변

#### inventory_order_node 핵심 패턴
- 자체 시스템 프롬프트(AGENT_SELLER_SYSTEM / AGENT_BUYER_SYSTEM) 보유
- orchestrator messages에서 라우터 JSON(`{"intent": ...}`)을 필터링하여 제외
- tool_calls 루프: `for round_idx in range(MAX_TOOL_ROUNDS)` — finish_reason=="stop"이면 break
- UUID 파라미터 자동 교정: `_fix_id_params()` 헬퍼로 seller_id/user_id/buyer_id 검증
- MAX_TOOL_ROUNDS 마지막 라운드 강제 break 제거 — validator_node가 tool_round < 2 기준으로 RETRY 관리하므로 두 로직 동시 존재 시 validator 발동 전에 루프 종료됨

#### AgentState 필드 (history 분리 — 히스토리 오염 해결)
```python
class AgentState(TypedDict):
    user_id, user_role, user_info, message, intent, subtype, target_year, target_month,
    history,           # 깨끗한 user/assistant 대화 히스토리 (DB 원본)
    messages,          # 라우터(orchestrator_node) 전용: system + history + 현재 user
    tool_results, tools_used, final_response, tool_round,
    validation_status, manual_review
```
- `messages` 는 라우터 시스템 프롬프트와 라우터 JSON 응답이 누적되어 오염됨
- 다른 노드(inventory_order/calendar_data/calendar_reason)는 모두 `state["history"]` 를 직접 사용 → 오염된 messages 를 다시 필터링할 필요 없음
- `AgentOrchestrator.run()` 에서 `clean_history` 를 한 번만 만들어 `history` / `messages` 양쪽에 주입

#### TOOL_FUNCTION_MAP 전체 목록 (18개)
```
get_products, check_stock, update_stock, create_product, delete_product, update_product,
get_orders, get_order_detail, update_order_status, create_order, delete_order,
find_sellers_by_product, find_buyers_by_product,
open_chat_room, get_calendar_events, create_calendar_event,
find_alternative_partners, get_user_profile
```

#### 시스템 프롬프트 고도화 패턴 (Phase 2)
- 12가지 CASE 안내를 AGENT_SELLER_SYSTEM / AGENT_BUYER_SYSTEM에 명시 → LLM이 도구 선택 실수 감소
- FEW_SHOT_EXAMPLES 모듈 상수로 분리 → 두 시스템 프롬프트에 공통 삽입 (문자열 연결)
- 권한 원칙(주문/상품 소유자 검증), 상품명 모호성 처리(조회 vs 삭제/수정 분기), 일정 중복 확인, 대체 거래처 추천 원칙을 프롬프트 섹션으로 분리 명시
- CASE-4: create_order 성공 시 create_calendar_event 즉시 자동 연쇄 호출 → 납품일 캘린더 자동 등록

#### send_chat_message needs_confirmation 응답 가이드 (2026-05-04 추가)
- 도구가 후보 채팅방 2개 이상 매칭 시 `success: false, needs_confirmation: true, candidates: [...], message_preview: ...` 형태로 반환되며 메시지는 발송되지 않음. LLM이 이 결과를 받았을 때 "보냈습니다"라고 잘못 답변하지 않도록 두 곳에 가이드 박음:
  - `AGENT_BASE_SYSTEM` 의 [채팅 메시지 발송 확인 가이드] 섹션 (라인 1007 근방, [주의사항] 직전) — SELLER/BUYER 합성본 양쪽 + response_node 까지 자동 반영. candidates 풀어쓰기 형식 예시, "1번"/"둘 다" 후속 응답 처리 규칙, fallback 발송 안내까지 포함.
  - `chat_node` 시스템 프롬프트의 [needs_confirmation 응답 가이드] 섹션 (라인 1884 근방, [채팅방 선택 규칙] 직후) — chat intent 라우팅 시 이 노드가 send_chat_message 를 가장 자주 호출하므로 직접 명시.
- 핵심 원칙: needs_confirmation: true 면 "메시지 보냈습니다" 절대 금지 → 후보를 자연어로 풀어 "(1) 옥수수 50kg 협상중 / (2) 옥수수 80kg 배송중 / 어느 방으로 보낼까요?" 형식으로 사용자에게 되묻기. 후속 응답에서 room_id 직접 지정 + 직전 message_preview 그대로 전달해 재호출.
- ⚠️ 단락회로 버그 수정 완료 (2026-05-03): `chat_node` 의 라인 1943~1949 가 LLM 자연어 응답을 정리한 `final_text` 를 사용하지 않고 하드코딩 "요청하신 메시지를 해당 채팅방에 전송했습니다." 만 반환해 needs_confirmation 안내·"어느 방으로 보낼까요?" 같은 되묻기·LLM 의 사정 설명 응답을 모두 묵살하던 버그였음. `content = (choice.message.content or "").strip()` → `final_text = content.replace("**", "").replace("- [", "[")` → `final_response: final_text or "요청을 처리하지 못했습니다. 다시 한 번 말씀해 주세요."` 로 교체. None 가드, 마크다운 정리, 빈 응답 fallback 동시 처리. 라인 1928 의 단일 즉시 발송 성공 단락회로 (`tool_calls 안 + '"success": true'`) 는 의도적으로 유지 (정상 동작).
- 단락회로 설계 원칙: tool_calls 가 **없는** finish_reason=="stop" 분기에서는 절대 하드코딩 메시지를 반환하지 말 것. LLM 이 도구 없이 자연어로만 응답하는 케이스 = 사용자에게 추가 정보를 묻거나 사정을 설명하는 케이스이므로 그 응답을 그대로 살려야 한다. 하드코딩 단락회로는 **tool 결과가 명확히 success=true 인 경우에만** 허용.
- 가독성 일관성: 별표/표/헤더 금지 원칙 그대로 유지. f-string placeholder 추가 없음 (일반 한국어 본문만 추가) → format KeyError 위험 0.

#### find_alternative_partners 트리거 강화 (2026-05-03)
- 도구 본문은 이미 구현돼 있었지만 시스템 프롬프트에 호출 트리거가 없어 LLM이 거의 호출하지 않던 문제. AGENT_BASE_SYSTEM 에 [대체 거래처 추천 가이드] 섹션 신설(트리거 3종 + 카테고리 자동 매핑 + 결과 풀어쓰기 원칙) → SELLER/BUYER 양쪽 합성본에 자동 반영.
- BASE 안에 `{role_label_short}` placeholder 추가 → `_SELLER_ROLE_VARS`/`_BUYER_ROLE_VARS` 에 "SELLER"/"BUYER" 매핑 신설. role_label_short 가 누락되면 format KeyError 가 나므로 BASE 에 새 placeholder 를 넣을 때는 두 ROLE_VARS 모두 동시 업데이트 필수.
- 역할별 미세 차이는 ROLE_APPENDIX 에서 분리: SELLER 는 "신규 구매자 발굴" 트리거(거래 끊긴 곳 대체), BUYER 는 "대체 공급처 추천" 트리거(평소 거래처 협상 결렬·납품일 충돌·재고 부족). 도구 시그니처 동일 — role 인자만 다르게.
- BUYER 모드 case2 가 "재고 부족 무조건 수용"이라 자체 재고 부족 트리거는 약하므로, 평소 거래처와 협상 결렬·가격 안 맞음·납품일 충돌 같은 외부 컨텍스트를 트리거로 명시해야 실제 호출이 일어남.

#### 새 tool 함수 패턴
- `open_chat_room`: chat_rooms 테이블 직접 조회, 양방향 검색(자신의 role에 따라 seller_id/buyer_id 배치)
- `get_calendar_events`: `calendar.monthrange(year, month)[1]`로 말일 계산, `.is_("deleted_at", None)` 패턴 준수
- `create_calendar_event`: order_id 빈 문자열이면 None으로 저장
- `find_alternative_partners`: BUYER→products+partners 조인, SELLER→order_items+partners 조인. 정렬 금지, LLM이 추천 순위 생성
- `get_user_profile`: user_id → username → company_name 우선순위 검색, asyncio 없이 동기 호출

### 주의사항 & 함정

- (구) orchestrator_node 가 라우터 JSON 을 messages 에 누적시켜 inventory_order_node 에서 이를 필터링해야 했음 → 현재는 `state["history"]` 필드를 별도로 두고 노드들이 그것을 직접 사용하므로 필터링 불필요. `_is_router_json()` 헬퍼는 잔존하지만 사용처 없음
- `response_format=json_object` 사용 시 시스템 프롬프트에 반드시 "JSON으로만 응답" 명시해야 함 (미명시 시 API 오류)
- 새 노드를 추가할 때는 `state["messages"]` 를 그대로 쓰지 말고 항상 `state["history"]` 를 사용한다. messages 는 라우터 전용
- response_node 단락회로: success=False 또는 재고 부족 결과는 반드시 LLM 통과시켜야 타협안 생성 가능. `last.get("message")` 유무만으로 단락회로 결정하면 이분법 거절 응답이 그대로 반환됨
- find_alternative_partners에 단순 정렬 공식 추가 금지 — DB 결과 그대로 반환, 추천 순위는 LLM(response_node)이 자연어로 생성

#### analyze_chat_consensus 구현 패턴 (Phase 3 검증)
- 동기 함수로 구현 (`get_openai_sync_client()` 동기 클라이언트) — `asyncio.run` 절대 사용 금지 (이벤트루프 충돌)
- `chat_ws.py`에서 반드시 `await asyncio.to_thread(analyze_chat_consensus, room_id)` 로 호출
- `response_format={"type": "json_object"}` + temperature=0 → 안정적인 JSON 반환
- LLM이 buyer_id/seller_id를 모를 수 있으므로 chat_rooms 조회 결과로 항상 덮어씀
- OPENAI_API_KEY 없거나 예외 발생 시 `{"status": "general", ...}` fallback → 서버 죽이지 않음
- `copy.deepcopy(_CONSENSUS_FALLBACK)` 패턴으로 fallback dict 공유 참조 오염 방지

#### connection_manager.py send_private_message 패턴
- `active_user_connections: dict[str, WebSocket]` 추가 — user_id → WebSocket 1:1 매핑
- `connect(room_id, websocket, user_id)` 시그니처에 user_id 추가 (기존 room_id 등록 + user_id 매핑 동시 처리)
- `disconnect(room_id, websocket, user_id=None)` — user_id 선택적, remove() 시 ValueError try/except 필수
- `send_private_message(user_id, message)` — ws 없으면 조용히 무시 (연결 끊긴 사용자 대상 무해)

#### chat_ws.py 합의 감지 통합 패턴
- broadcast 직후 `if should_analyze(room_id):` 블록에서 `asyncio.to_thread` 호출
- 합의 감지 전체 블록을 try/except로 감싸 실패해도 WebSocket 연결 유지
- consensus 후속 처리(`_handle_consensus`) 내부도 각 단계별 try/except — product 미매칭 시 주문 스킵 후 시스템 메시지만 broadcast
- rejected 후속 처리(`_handle_rejected`) — `_infer_category(product_name)` 헬퍼로 카테고리 추론, 매칭 실패 시 "VEGETABLE" 기본값
- `last_analysis` 인메모리 dict는 서버 재시작 시 초기화 — 의도된 동작, 영속성 불필요
