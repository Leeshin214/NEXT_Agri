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
| 채팅 답장 초안 | POST /chat/draft | 채팅방 컨텍스트 기반 답장 본문 초안 (메시지 DB 저장 X). `services/draft_service.generate_chat_draft` |
| 재고 분석 | POST /ai/inventory-alert | 재고 현황 분석 및 경고 |
| 채팅 합의 감지 | agent_tools.analyze_chat_consensus | 채팅 메시지 → 합의/협상/거절/일반 분류, 합의 시 주문·캘린더 자동 생성 (AgenticPay) |
| 채팅 협상 의도 감지 | services.negotiation_detection_service | 평문 메시지 → 품목/수량/단가 추출. confidence>=0.7 만 metadata.draft_negotiation 저장 + 발신자 본인에게만 WS push. **자동 등록 X** (사용자 [등록] 클릭 필수). |
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

#### TOOL_FUNCTION_MAP 전체 목록 (36개, 2026-05-04 갱신)
```
# 상품/재고
get_products, check_stock, update_stock, create_product, delete_product, update_product,
# 주문
get_orders, get_order_detail, update_order_status, update_order, create_order, delete_order,
# 거래처/검색
find_sellers_by_product, find_buyers_by_product, find_alternative_partners, get_user_profile,
# 채팅
open_chat_room, get_chat_rooms, get_chat_messages, send_chat_message,
# 캘린더
get_calendar_events, create_calendar_event, update_calendar_event, delete_calendar_event,
# 거래처 등록 (양방향 PENDING)
request_partner_registration, request_partner_registration_by_name,
# 카운터오퍼 / 납품일 변경 (2026-05-04 신규)
submit_counter_offer, accept_counter_offer, reject_counter_offer,
submit_delivery_date_change, accept_delivery_date_change, reject_delivery_date_change,
# 정기배송 V1.6 양방향 승인 모델 (2026-05-04 신규, 테스터 피드백 #6)
create_subscription_request, accept_subscription_request, reject_subscription_request,
create_subscription_from_order,
```
- TOOLS 리스트 (orchestrator.py inventory_order_node 노출용) 도 동일하게 30개 (carbon copy 가 아님 — `analyze_chat_consensus` / `_resolve_chat_room_candidates` / `_do_send_chat_message` 등 내부 헬퍼 6종은 제외).

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

#### negotiation_detection_service 구현 패턴 (US-2, 2026-05-04)
- `analyze_chat_consensus` 와 다르게 **비동기 async 함수** + `get_openai_client()` 사용 — `BackgroundTasks` 가 동일 이벤트 루프에서 실행되므로 await 가능 (asyncio.to_thread 래핑 불필요).
- POST `/chat/rooms/{room_id}/messages` 라우터에서 `BackgroundTasks.add_task(process_message_for_negotiation, ...)` 로 전달 → 응답 시간에 영향 X.
- `response_format={"type": "json_object"}` + `temperature=0.0` + `max_tokens=200` → 토큰 절약 + 결정적 출력.
- 시스템 프롬프트 핵심: "B2B 농산물 채팅에서 가격 협상 의도 감지", confidence 가이드 명시 (셋 다 명확하면 0.85+, 둘만 있으면 0.6 이하, 잡담 0.2 이하), few-shot 예시 (옥수수 50kg 7만원 → 0.9 / 안녕하세요 → 0.0) 포함.
- `room_context` 에 (있으면) 연결 주문의 상품 후보를 채워넣어 LLM 추론 가이드. order_id 없으면 빈 리스트.
- `_normalize_detection_result` 가 LLM 출력을 강제 정규화 — 음수/0/문자열 콤마 단가 등 모두 안전 처리. 의미 없는 감지(product_name + quantity + unit_price 모두 None)는 None 반환해 호출 측에서 즉시 skip.
- WS push 는 `manager.send_private_message(sender_id, payload)` — 채팅방 broadcast 가 아니므로 상대방은 절대 못 봄. 동일 user 다중 탭 모두 받음.
- 모든 예외는 try/except 로 흡수 — `process_message_for_negotiation` 외부에서 raise 가 발생해도 chat 흐름이 안 막히도록.

#### detect vs consensus 분리 정책 (검증된 설계)
- `analyze_chat_consensus` (chat_ws.py 안에서 호출) — 합의/거절 감지 시 **자동으로** 주문 INSERT + 캘린더 등록 + 시스템 메시지 broadcast.
- `negotiation_detection_service` (chat.py 라우터에서 호출) — 단순 협상 의도 감지 + metadata 저장 + 본인에게만 알림 → **사용자 [등록] 클릭 시에만** propose_counter_offer 호출.
- 두 흐름은 동시 동작 가능 (한 메시지가 협상 의도 + 합의 양쪽 트리거 가능). consensus 가 먼저 자동 주문을 만들어도 draft_negotiation 은 별도 metadata 키라 충돌 없음.

#### Phase B 시스템 프롬프트 보강 (2026-05-04)
- 새 도구 12개(submit/accept/reject_counter_offer, submit/accept/reject_delivery_date_change, request_partner_registration, request_partner_registration_by_name, create/accept/reject_subscription_request, create_subscription_from_order)에 대한 자연어 트리거 가이드 5종을 시스템 프롬프트에 분산 추가:
  - `AGENT_BASE_SYSTEM` — [채팅 메시지 발송 확인 가이드] 직후·[주의사항] 직전에 (1) 자연어 → 카드 도구 자동 호출 핵심 매핑, (2) 자연어 → 카드 도구 안전장치, (3) 재고 검색 vs 대체 거래처 분리 원칙(환각 방지) 3개 섹션. SELLER/BUYER 합성본에 자동 반영.
  - `chat_node` 시스템 프롬프트 — [needs_confirmation 응답 가이드] 직후에 (1) 자연어 협상/납품일 → 카드 도구 매핑, (2) 거래처 등록 / 정기배송 자연어 매핑, (3) 재고 vs 대체 분리 3개 섹션 직접 명시(chat intent 라우팅 시 가장 자주 호출되는 노드라 BASE 와 별도로 보강).
- 핵심 안전장치: 가격/날짜/주기 같은 필수 정보가 발화에서 빠지면 도구 호출 X → 되묻기. 정보가 명확히 있으면 이중 confirmation 없이 즉시 호출(UX). 카드는 즉시 발송되어 채팅방에 PENDING 으로 노출되므로 도구 호출 직후 "○○으로 카드를 보냈습니다. 상대방이 수락/거절하면 알려드릴게요" 형식의 후속 흐름 안내 강조.
- 환각 방지: "참치 찾아줘" → product_name='참치'만 정확 검색. 0건이라도 새우/연어 같은 다른 품목 추천 절대 금지. 사용자 명시 동의 후에만 find_alternative_partners 호출. 1차 검색 도구와 대체 거래처 도구를 같은 라운드에 동시 호출 금지.
- 도구 시그니처는 실제 함수 정의 그대로 매핑 (notes/proposed_total_amount/proposed_delivery_date/offer_id/change_id 등 실제 키 사용). placeholder 추가 없음 → KeyError 위험 0. AST OK, SELLER/BUYER 합성본 모두 _render_agent_system 통과 확인 완료.

#### 구매자 주문/견적 생성 가이드 (2026-05-04 갱신 — auto_confirm 제거, delivery_date 필수화)
- 백엔드(`order_service.create_order`)가 다음과 같이 바뀌었다:
  - **delivery_date 필수화** — `OrderCreate` 스키마 / `agent_tools.create_order` / orchestrator `TOOLS` schema 의 required 모두 강제. 빠지면 422.
  - **가격 일치 시 CONFIRMED 자동 진입 제거** — 모든 신규 주문은 `QUOTE_REQUESTED` 견적 상태로 시작해 판매자 검토를 기다린다. (이전엔 `unit_price >= price_per_unit` 일 때 즉시 CONFIRMED + 재고 차감 했지만, 이제는 판매자가 명시적으로 수락해야 확정.)
  - **가격 협상 분기는 유지** — `unit_price < price_per_unit` 일 때만 자동 카운터오퍼 → NEGOTIATING + PENDING 카드.
- 시스템 프롬프트가 옛 흐름 ("가격 일치 → CONFIRMED 자동")을 전제로 작성돼 있어 사용자에게 "주문이 확정됐습니다"라고 거짓 답변하던 문제 → 두 위치를 새 흐름에 맞게 교체.
- 적용 위치 (orchestrator.py):
  - `BUYER_ROLE_APPENDIX` 의 `[🚨 구매자 주문/견적 생성 규칙]` (라인 1572 근방) — 기존 `[🚨 구매자 주문/견적 생성 규칙 — 자동 확정 / 협상 분기]` + `[🚨 단가 자동 조회 강제]` + `[🚨 주문 생성 결과 응답 표현]` 3개 섹션을 합쳐서 `[🚨 구매자 주문/견적 생성 규칙]` + `[🚨 단가 / 납품일 필수 확보]` + `[🚨 주문 생성 결과 응답 표현]` + `[🚨 납품일 변경]` 4개 섹션으로 재구성.
  - `chat_node` 시스템 프롬프트의 `[구매자 자동 주문 확정 / 협상 분기 가이드]` (라인 2427 근방) — `[구매자 주문/견적 생성 가이드]` 로 교체.
- 핵심 발화 패턴 (5종):
  1. **납품일 + 수량 명시** ("망고 2kg 5월 20일에 받게 주문해줘") → `check_stock`/`find_sellers_by_product` 로 `price_per_unit` 조회 → `unit_price` 채우고 날짜를 'YYYY-MM-DD' 정규화 → `create_order` → QUOTE_REQUESTED.
  2. **가격까지 명시** ("13만원에 망고 2kg 5/20일 받기로 주문해줘") → 명시 가격 + 날짜 그대로 → 일치/이상이면 QUOTE_REQUESTED, 낮으면 NEGOTIATING + 카운터오퍼.
  3. **납품일 빠짐** ("망고 2kg 주문해줘") → `create_order` 호출 금지. "납품일은 언제로 할까요? (예: 5월 20일)" 라고 자연체로 되묻고 사용자 답변 받기 전까지는 대기. "오늘"/"내일" 같은 모호한 표현을 LLM 임의로 날짜로 바꿔치기 금지.
  4. **협상 명시** ("깎아줘", "할인 받고 싶어") → `submit_counter_offer` (이미 PENDING/NEGOTIATING 주문 있을 때). 가격 함께 언급된 새 주문이면 납품일 받아낸 뒤 그 가격으로 `create_order`.
  5. **수량만 + 의도 모호** ("망고 2kg") → 의도 확인 + 납품일 확보.
- 필수 확보 강제: `unit_price` 와 `delivery_date` 둘 다 비어있으면 안 됨. 단가는 조회 도구로 확보, 납품일은 사용자에게 받아낼 때까지 호출 금지.
- 응답 표현 가이드 (별표/표/헤더 금지, 자연체, **"주문이 확정됐습니다" 절대 금지**):
  - QUOTE_REQUESTED (정상 신규 견적): "○○ ○단위 주문 견적을 판매자에게 보냈습니다. 가격 ₩○○, 납품일 ○월 ○일. 판매자가 수락하면 알려드릴게요."
  - NEGOTIATING (가격 협상 시작): "○○ ○단위 주문에 대해 ₩○○으로 협상가를 제시했습니다. 채팅방에 카드를 발송했고, 판매자가 수락/거절하면 알려드릴게요."
  - 그 외: "주문이 접수됐고 판매자 확인을 기다리고 있습니다."
- 납품일 변경 (`submit_delivery_date_change`): QUOTE_REQUESTED 단계면 "판매자가 견적을 검토하는 중이라 변경 요청도 함께 전달했습니다" 같이 자연스럽게 안내.
- placeholder 추가 없음. AST OK, render 후 잔여 placeholder 0개, BUYER 합성본에 새 가이드 9개 marker 모두 포함, SELLER 합성본 누출 0건, 옛 표현 4종("자동 확정 / 협상 분기", "auto_confirmed=true", "재고를 자동 차감한다", "[🚨 단가 자동 조회 강제]") 모두 제거 확인 완료.
- 주의: SELLER 합성본에는 의도적으로 추가하지 않음 — 판매자는 `create_order` 권한 없음. SELLER 의 주문 확정은 `update_order_status(new_status="CONFIRMED")` 흐름.

#### 검증된 패턴: "수치를 먼저 제시하는 응답 형식이 더 효과적" (2026-05-04 추가)
- 응답 표현 예시를 가이드에 박을 때 "○○ N단위 주문 견적을 판매자에게 보냈습니다. 가격 ₩○○, 납품일 ○월 ○일." 처럼 수치 (수량·가격·날짜) 를 먼저 풀어서 제시하는 형식이, "주문 견적이 발송됐고 가격은 ₩○○이고 납품일은 ○월 ○일입니다" 처럼 산문체로 풀어쓰는 형식보다 LLM 모방률이 높음.
- 이유: GPT-4o-mini 는 가이드의 마지막 예시 문장을 그대로 따라가는 경향이 있어, **명사 + 수치 + 핵심 정보를 마침표로 끊어 나열**하는 패턴이 채팅창에서 가독성도 좋고 LLM 도 잘 재현함.
- 반대로 부정형 ("절대 X 라고 말하지 마라") 은 한 번 더 강조 — `[응답 표현]` 섹션 본문 + 헤더 옆 강조 + 가이드 맨 마지막 문장 3중으로 박아야 LLM 이 무의식적으로 옛 표현으로 돌아가는 걸 막을 수 있음 (이번 작업에서 "주문이 확정됐습니다 절대 금지"를 3곳에 분산 명시).

#### 주문 대상 판매자 식별 절차 + 도구 실패 시 환각 방지 (2026-05-04 갱신 — 우선순위 재정의)
- 실제 사용자 시나리오 실패: "test3한테 감자 10kg 주문해줘" → AI 가 `create_order(seller_id="test3")` 처럼 이름을 UUID 자리에 직접 넣어 호출 실패 + 그 후 환각으로 컨텍스트 메모리에 있던 다른 주문(동해 참치·참나물 등)을 줄줄이 노출. 두 가지 결함을 동시에 강제로 차단해야 한다.
- (1) **schema description 강화** (orchestrator.py 라인 ~423-434): `create_order` 의 `seller_id` 와 `buyer_id` description 에 "이름/회사명 평문 금지", "get_user_profile / find_sellers_by_product 로 UUID 조회 후 사용", "UUID 아닌 값은 백엔드가 즉시 실패시킨다"를 명시. JSON schema description 은 OpenAI 가 tool_call 인자 생성 시점에 직접 참조하므로, 이 위치에서 막는 것이 BUYER_ROLE_APPENDIX 본문 가이드보다 LLM 준수율이 더 높다.
- (1.5) **find_sellers_by_product schema description 보강** (라인 ~520): description 끝에 "응답의 seller_id 는 UUID 형식이라 create_order 의 seller_id 에 그대로 사용 가능. 사용자가 직후 발화에서 회사명/담당자만 언급해도 이 응답을 컨텍스트로 활용해 다시 get_user_profile 을 호출할 필요 없이 매칭되는 항목의 seller_id 를 그대로 쓸 것" 추가. find_*_by_product 응답을 다음 발화의 컨텍스트로 활용하는 패턴을 schema 차원에서 LLM 에게 알려줌.
- (2) **BUYER_ROLE_APPENDIX `[🚨 주문 대상 판매자 식별 절차 — 매우 중요]` 섹션 (라인 ~1770)** — 우선순위 명시 버전. 1단계 get_user_profile 부터 부르라고 박았던 옛 가이드는 LLM 을 ILIKE 매칭 실패로 유도해 "거래처 찾을 수 없다" 잘못된 응답 양산. **컨텍스트에 이미 seller_id 가 있으면 그것부터 쓰는 게 정답**. 새 우선순위 4단계로 재구성:
  - **[1순위 — 직전 대화 컨텍스트 활용]** 직전 find_sellers_by_product / find_buyers_by_product 응답의 seller_id 를 그대로 사용. seller_name / seller_company / username 매칭만 해서 create_order 호출. **이미 컨텍스트에 UUID 가 있는데 굳이 get_user_profile 다시 부르지 마라**.
  - **[2순위 — 새로 검색]** 직전 컨텍스트에 판매자 목록이 없거나 사용자가 새 품목 언급 → find_sellers_by_product(category, product_name) 호출 → seller_id 사용.
  - **[3순위 — get_user_profile 폴백]** 사용자가 품목 정보 없이 거래처 이름만 언급해서 find_sellers_by_product 를 못 부르고 직전 컨텍스트에도 매칭이 없을 때**만** get_user_profile(username/company_name) 호출. ILIKE 부분 일치라 정확 매칭 안 될 수 있음을 명시. 0건이면 사용자에게 정확한 이름 되묻기.
  - **[금지 사항]** 명시적 단정문 4종: 이름을 seller_id 에 그대로 넣지 마라 / UUID 추측 금지 / 응답에 이미 seller_id 가 있는데 get_user_profile 다시 부르지 마라 / 안 물은 다른 정보(이전 주문, 다른 거래처) 끌어오지 마라.
  - **[다중 매칭]** 1순위/2순위 결과에서 후보 2명 이상이면 도구 호출 X, 사용자에게 자연체로 되묻기.
- (3) **chat_node 시스템 프롬프트 동일 섹션 (라인 ~2677)** 에도 동일한 4단계(우선순위 + 금지 + 다중매칭) 매핑을 직접 명시. chat intent 라우팅 시 가장 자주 호출되는 노드라 BUYER_ROLE_APPENDIX 와 별도로 박음 — 5중 명시 패턴 일부.
- (4) **AGENT_BASE_SYSTEM 신규 섹션** `[도구 실패 시 응답 가이드 — 매우 중요 (환각 방지)]` (라인 ~1591 근방, [재고 검색 vs 대체 거래처 추천 분리 원칙] 직후, [주의사항] 직전): SELLER/BUYER 합성본 양쪽에 자동 반영. 핵심 원칙 6개 — (a) 실패 사실+원인을 한 줄, (b) 안 물은 다른 정보 끌어와 늘어놓지 마라, (c) 다음 액션 1개만 짧게, (d) 실패를 성공으로 포장 금지, (e) 컨텍스트 메모리의 다른 주문/거래처 자기멋대로 노출 금지, (f) error 코드 영문 그대로 노출 금지.
- (5) **chat_node** 에도 동일한 [도구 실패 시 응답 가이드] 섹션을 직접 명시. BASE 안에서도 들어가지만, chat 라우팅이 가장 자주 도구 실패를 마주치는 노드라 중복 명시 — 5번 정도가 LLM 망각을 가장 잘 방어하는 표준 패턴 (가독성/마크다운 금지 가이드도 같은 5중 패턴).
- 검증 결과: AST OK, placeholder 11개 모두 보존 (`role_label`, `role_label_short`, `case1/2/10/11_action`, `auth_product_rule`, `ambiguity_modify_rule`, `user_id`, `company_name`, `user_name`), BUYER 합성본 잔여 placeholder 0, SELLER 합성본 잔여 placeholder 0, BUYER 전용 가이드(`주문 대상 판매자 식별 절차`)가 SELLER 합성본에 누출 0건, 도구 실패 가이드는 BASE 에 박힌 결과 SELLER/BUYER 양쪽 자동 반영 확인. 이전 가이드 14종(가독성, 핵심 대화 원칙, 대체 거래처, send_chat_message needs_confirmation, 자연어→카드 도구, 안전장치, 재고 vs 대체, 구매자 주문/견적, 단가/납품일 필수, 주문 결과 응답 표현, 납품일 변경, 채팅방 연결, 신규 구매자 발굴, 카드 도구 매핑) 모두 보존.
- 회귀 검증 통과: "자동 확정 / 협상 분기", "auto_confirmed=true", "재고를 자동 차감한다", "[🚨 단가 자동 조회 강제]" 등 옛 표현 모두 미존재.
- 핵심 교훈: **이름→UUID 매핑 가이드는 LLM 본문 프롬프트보다 schema description 에 박아야 효과 있음.** OpenAI tool_call 은 schema 의 description 을 인자 생성 직전에 다시 읽어 들이므로, "이 필드는 UUID 만 받음"을 schema 차원에서 못 박으면 LLM 이 평문(이름)을 넣을 확률이 거의 사라진다. 본문 프롬프트는 보조 — schema 가 1차 방어선.
- 핵심 교훈 2: **도구 실패 시 환각 방지는 "안 물은 정보 끌어오지 마라"를 명시적으로 박아야 함.** 단순히 "에러를 정확히 안내하라"만 박으면 LLM 이 친절을 가장해 컨텍스트 메모리의 다른 주문/거래처를 줄줄이 추가로 노출한다. "사용자가 직접 물은 대상의 에러만 답한다"를 본문에 단정문으로 박아야 멈춘다.
- 핵심 교훈 3 (2026-05-04 신규 — 우선순위 가이드 회귀 사고에서 학습): **"가장 정확한 도구를 부르라"는 본능적 직관이 오히려 함정**. 옛 가이드가 "1단계: get_user_profile 호출"을 우선순위 맨 위에 둔 이유는 "사용자 이름 → user 테이블 정확 조회"가 가장 직관적이기 때문이지만, 실제로는 (a) ILIKE 부분 일치라 정확히 매칭 안 될 수 있고 (b) 직전 대화 컨텍스트의 seller_id 를 무시하게 만들어 이미 확보된 UUID 를 버리고 다시 검색하는 비효율 + 매칭 실패 흐름을 유발했다. **"컨텍스트에 이미 답이 있으면 그것부터 쓰라"가 1순위여야 한다.** LLM 가이드를 쓸 때 "어느 도구를 부르라" 가 아니라 "현재 상태 → 가장 적은 도구 호출로 정답 도달"의 결정 트리를 먼저 박아야 한다. find_*_by_product 같이 응답에 UUID 가 포함된 도구는 그 응답이 곧 다음 라운드의 컨텍스트가 됨을 schema description 에서도 함께 알려주면 LLM 이 자연스럽게 컨텍스트 활용 흐름을 따라간다.
- 핵심 교훈 4 (2026-05-04 — 명령형 어조의 효과): "다시 부르지 마라" 같은 부정 명령형 + 구체 예시("seller_id='test3' 같이 넣지 마라")를 같이 박는 것이 "권장합니다" 같은 산문체보다 LLM 준수율이 훨씬 높음. **금지 사항은 본문에 단정문 + 헤더 옆 강조 + 구체 anti-example** 3중 패턴이 표준 — 이번 작업에서 [금지 사항] 섹션에 4종 단정문을 박아 옛 우선순위로 회귀하지 않도록 봉쇄.

#### get_orders 도구 — service 위임 + status_in 다중 상태 (2026-05-04 추가)
- 기존 `agent_tools.get_orders` 가 (1) `.is_("deleted_at", None)` 누락으로 삭제된 주문도 응답에 포함되고 (2) 단일 `status` 만 받아 사용자의 "진행 중인 주문" (UI 의 5상태 다중 정의: `QUOTE_REQUESTED, NEGOTIATING, CONFIRMED, PREPARING, SHIPPING`) 같은 발화를 표현 못하던 두 가지 결함이 있었다 → `order_service.list_orders` 위임 패턴으로 동시 해결.
- **위임 패턴**: 도구 본문에서 직접 `supabase.table("orders").select(...)` 를 호출하지 않고 `_run_async_in_thread(lambda: order_service.list_orders(user_id=..., role=..., status=status, status_in=status_in, page=1, limit=20))` 으로 service 의 비동기 메서드 호출. service 가 이미 `deleted_at IS NULL` + `status_in` 다중 + 페이지네이션 + buyer/seller/items 임베딩을 일관 처리하므로 도구는 응답을 LLM-친화 형식으로 재가공만 한다.
- **시그니처**: `def get_orders(user_id, role, status: Optional[str]=None, status_in: Optional[list[str]]=None) -> dict`. 기존 호출 (`status=...`) 은 그대로 동작 (하위호환). status_in 우선 적용은 service 레이어에서 결정.
- **schema description 강화** (orchestrator.py `TOOLS` 의 `get_orders` 엔트리): "사용자가 '진행 중', '활성', '내 주문' 등 표현 시 `status_in=['QUOTE_REQUESTED','NEGOTIATING','CONFIRMED','PREPARING','SHIPPING']` 로 호출. 완료/취소 제외" 를 명시. enum 도 7종 모두 박음 (단일 `status` 와 동일). LLM 이 schema description 을 tool_call 인자 생성 직전에 직접 읽으므로, 다중 상태 매핑은 본문 프롬프트보다 schema 에 박는 것이 준수율이 높다.
- **LLM 응답 contract 보존**: `_flatten_order_row` 가 채워주는 `items: [...]` 에서 `product_name`/`product_unit`/`quantity`/`unit_price` 를 다시 모아 `product_summary` / `primary_product_name` / `primary_quantity` / `primary_unit_price` / `primary_subtotal` / `item_summary` / `items_count` 7종 derived 필드를 도구 응답에 추가한다 — 시스템 프롬프트 (`AGENT_BASE_SYSTEM` 라인 1643-1644 "product_summary 또는 primary_product_name 이 상품명과 일치", chat_node 라인 2542 "get_chat_rooms 결과의 product_summary, primary_quantity, item_summary") 가 이 필드명으로 주문 매칭/선택을 지시하므로 service 응답을 그대로 노출하면 안 됨. 임베딩 객체(`buyer`/`seller`/`items`) 는 응답에서 제거 → LLM 토큰 절약.
- **검증 패턴 (venv 없는 환경에서도 통과)**: AST 로 `get_orders` body 를 unparse 한 뒤 `"order_service.list_orders" in body` / `"_run_async_in_thread" in body` / `"product_summary" in body` 등 substring assertion. 동시에 `ast.literal_eval(TOOLS_node)` 로 orchestrator 의 `TOOLS` list 를 파싱해 `status_in` properties 가 `type:"array"`, `items.enum` 7종 보유하는지 검증 + `json.dumps(tool_entry)` round-trip 으로 OpenAI tool calling 포맷 준수 확인. 동일 패턴이 다른 schema 변경 검증에도 재사용 가능.
- **`_execute_tool` 의 kwargs 호출 (`func(**tool_input)`) 덕분에 새 파라미터 추가가 안전**: 기존 `INT_FIELDS` 변환 로직과 충돌 없음. list 파라미터는 OpenAI 가 array 로 직접 보내주므로 별도 변환 불필요. dispatch 코드 변경 없이 도구 함수 + schema 두 곳만 갱신하면 된다.
- **service 위임의 부수 효과 — 정렬/페이지네이션도 통일**: 기존 도구는 `.order("created_at", desc=True).limit(20)` 직접 박고 있었는데 service.list_orders 도 동일 (`order("created_at", desc=True).range(...)`) 이라 응답 순서/개수는 그대로 유지. 향후 service 가 정렬·페이지 정책을 바꾸면 도구도 자동 따라간다.
- **확장 가이드**: `agent_tools.get_chat_rooms` 도 같은 패턴 (직접 supabase 호출 + 자체 flatten) 인데 `chat_room_service` 가 있다면 위임으로 통일 가능. 다른 도구 (`get_calendar_events`, `find_alternative_partners`) 는 deleted_at 필터를 직접 챙기고 있으니 이번 함정 대상은 아님 — 신규 도구 추가 시 "service 가 있으면 무조건 위임" 을 1순위 패턴으로 적용할 것.

#### get_orders 자연어 → status_in 매핑 + 응답 환각 방지 가이드 (2026-05-04 추가)
- schema description 만으로는 LLM 이 사용자의 다양한 한국어 표현을 정확히 status_in 으로 옮긴다는 보장이 부족. tool_call 인자 생성 직전 schema 를 읽기는 하지만, 자연어 → enum 다중 매핑은 본문 프롬프트와 schema description 양쪽에 동시에 박아야 LLM 이 일관되게 호출한다. 또한 `get_orders` 결과 응답 표현 규칙(환각 방지)도 함께 박아야 "협상 요청 중" / "상태 없음" / "검토 중" 같이 enum 에 없는 LLM 임의 표현을 막을 수 있다.
- 적용 위치 (orchestrator.py):
  - `AGENT_BASE_SYSTEM` 의 `[주문 목록 조회 가이드 — 자연어 → status_in 매핑 (매우 중요)]` (라인 1623 근방, [재고 검색 vs 대체 거래처 추천 분리 원칙] 직후, [도구 실패 시 응답 가이드] 직전) + `[주문 응답 표시 규칙 — 환각 방지]` (라인 1637 근방). SELLER/BUYER 합성본 양쪽에 자동 반영. response_node 의 요약 단계에서도 BASE 가 적용되므로 한 곳에 박는 것으로 전체 흐름 커버.
  - `chat_node` 시스템 프롬프트의 동일 두 섹션 (라인 2625 / 2633 근방, [도구 실패 시 응답 가이드] 직후, [자연어 협상/납품일 → 카드 도구 매핑] 직전). chat intent 라우팅 시 사용자가 "주문 보여줘" / "진행 중인 주문 확인" 같이 자연어로 가장 자주 묻는 노드라 BASE 와 별도로 직접 명시 — 5중 패턴(BASE + chat_node + schema description) 의 일부.
- 자연어 매핑 핵심 (8종):
  1. "진행 중인 주문" / "활성 주문" / "내 주문" / "오픈된 주문" / "처리 중 주문" → `status_in=["QUOTE_REQUESTED","NEGOTIATING","CONFIRMED","PREPARING","SHIPPING"]` (5상태)
  2. "완료된 주문" / "끝난 주문" → `status_in=["COMPLETED"]`
  3. "취소된 주문" / "취소건" → `status_in=["CANCELLED"]`
  4. "협상 중 주문" → `status_in=["NEGOTIATING"]`
  5. "확정된 주문" → `status_in=["CONFIRMED"]`
  6. "배송 중 주문" → `status_in=["SHIPPING"]`
  7. "준비 중 주문" / "출고 준비 중" → `status_in=["PREPARING"]`
  8. "견적 요청" / "들어온 견적" → `status_in=["QUOTE_REQUESTED"]`
  9. **상태 미명시** ("주문 보여줘" / "주문 목록") → 진행 중 기본값 (5상태). 완료/취소는 사용자가 명시 요청해야 포함.
- 응답 표시 규칙 핵심 (환각 방지 5종):
  - status enum 한글 매핑 고정: `QUOTE_REQUESTED→"견적 요청"`, `NEGOTIATING→"협상 중"`, `CONFIRMED→"주문 확정"`, `PREPARING→"준비 중"`, `SHIPPING→"배송 중"`, `COMPLETED→"완료"`, `CANCELLED→"취소"`. 임의 표현("협상 요청 중", "상태 없음", "검토 중", "보류") 금지.
  - 도구가 반환하지 않은 주문은 절대 응답에 포함 금지 — 컨텍스트 메모리/이전 대화에 옛 주문이 기억나도 출력 X. 사용자가 직접 묻지 않은 다른 주문(어제 본 견적, 옛 참치 주문)을 끌어와 답하지 말 것.
  - 0건이면 "현재 진행 중인 주문이 없습니다" 또는 "조회된 주문이 없습니다" 만 안내. 거래처 추천·다른 카테고리 주문·상품 정보 늘어놓지 말 것.
  - 마크다운 강조·표·헤더 금지(가독성 일관). 자연체 한국어 + 필요 시 `1.` 번호.
  - 응답 예시는 수치(품목·수량·날짜·금액) 우선 형식: `"옥수수 50kg — 협상 중, 납품일 5월 20일, ₩600,000"` — 검증된 패턴 ("수치를 먼저 제시하는 응답 형식이 더 효과적") 그대로 적용.
- 검증 결과: AST OK, placeholder 11/11 보존, 잔여 placeholder 0(SELLER/BUYER 양쪽), 신규 가이드 BASE + chat_node 모두 포함, BUYER 전용 가이드 SELLER 누출 0건, 옛 표현 회귀 0건, 이전 가이드 26종 모두 보존.
- **핵심 교훈 — 다중 enum 매핑은 schema + 본문 5중 명시**: 단일 status 만 있을 때는 schema description 한 줄로 충분했지만 status_in 처럼 LLM 이 다중 enum 배열을 추론해야 하는 파라미터는 (1) schema description 의 enum + 매핑 안내, (2) BASE 본문의 [주문 목록 조회 가이드] 8종 매핑, (3) chat_node 의 동일 매핑 — 3중으로 박아야 LLM 이 "진행 중인 주문" 같은 자연어 발화를 정확히 5상태 배열로 변환한다. schema 만 있으면 LLM 이 자주 단일 status 만 보내고 다른 4상태를 누락시키는 사례가 있어 본문 프롬프트가 백업 역할을 한다.
- **핵심 교훈 — 응답 표시 규칙은 enum 매핑까지 명시 박아야 환각 차단**: 도구 결과의 status 값을 그대로 LLM 에 던져주면, GPT-4o-mini 가 "협상 요청 중" / "상태 없음" 같이 enum 에 없는 한국어 표현을 자기 멋대로 만들어내 사용자 혼란을 유발한다. "이 매핑만 사용" + 한글 표 7종을 본문에 박으면 LLM 이 곧이곧대로 따라가 일관된 표현이 나온다. 부정형("X 라고 말하지 마라")은 한 번 더 강조해서 본문 + 헤더 옆 강조 + 마지막 문장 3중으로 박는 패턴을 그대로 유지.
