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

#### TOOL_FUNCTION_MAP 전체 목록 (41개, 2026-05-04 갱신)
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
# 거래처 (조회 / 등록 / 응답)
get_partners,                                  # 2026-05-04 신규 — ACTIVE/PENDING_OUTGOING/PENDING_INCOMING/INACTIVE 조회
request_partner_registration, request_partner_registration_by_name,
get_incoming_partner_requests, accept_partner_request, reject_partner_request,
# 정기배송 받은 요청
get_incoming_subscription_requests,
# 카운터오퍼 / 납품일 변경 (2026-05-04 신규)
submit_counter_offer, accept_counter_offer, reject_counter_offer,
submit_delivery_date_change, accept_delivery_date_change, reject_delivery_date_change,
# 정기배송 V1.6 양방향 승인 모델 (2026-05-04 신규, 테스터 피드백 #6)
create_subscription_request, accept_subscription_request, reject_subscription_request,
create_subscription_from_order,
```
- TOOLS 리스트 (orchestrator.py inventory_order_node 노출용) 도 동일하게 30개 (carbon copy 가 아님 — `analyze_chat_consensus` / `_resolve_chat_room_candidates` / `_do_send_chat_message` 등 내부 헬퍼 6종은 제외).
- 모듈 분포 (PR 3 완료 시점, 2026-05-04): `agent/tools/product.py` (6) + `agent/tools/order.py` (6) + `agent/tools/partner.py` (7) + `agent/tools/subscription.py` (4) + `agent/tools/negotiation.py` (6) + `agent/tools/user.py` (4) + `agent/tools/calendar.py` (4) + `agent/tools/chat.py` (3) = **40 도구 registry 등록**. 잔존 1 (`get_incoming_subscription_requests`) 은 agent_tools.py 에 본문 + TOOL_FUNCTION_MAP 직접 추가 → 외부 노출 41. `analyze_chat_consensus` 는 `agent/tools/chat.py` 에 본문 있지만 `@tool` 미부착 → registry 미등록 (chat_ws.py 직접 import 전용).

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

#### 카드 도구(submit_counter_offer / submit_delivery_date_change) order_id 결정 절차 가이드 (2026-05-04 추가)
- 실제 사용자 시나리오 실패: "테스트 관리 협상가를 30000원으로 제시해줘" (사용자가 어느 상품인지 명시 안 함, "테스트 관리"는 단순 지시어) → AI 가 진행 중인 주문 두 건(대파 10kg / 새우 10kg) 중 임의로 새우를 선택해 "새우 주문에 ₩30,000으로 가격 협상 요청을 하겠습니다" 응답. 사용자 의도와 무관한 주문에 협상가를 보내는 위험한 동작.
- 원인: 카드 도구(submit_counter_offer / submit_delivery_date_change / accept_* / reject_* 6종)는 `order_id` 가 필수인데, LLM 이 모호한 발화에서 후보 여러 개를 마주쳤을 때 "친절을 가장해" 한 후보를 선택하는 환각 패턴이 있음. "어느 주문인지 물어봐라" 가이드는 [자연어 → 카드 도구 매핑] 섹션 안에 있었지만 매핑 규칙 가이드와 섞여 있어 LLM 이 무시함.
- 해결책 — 독립 섹션으로 분리해서 결정 트리 명시:
  - **AGENT_BASE_SYSTEM** 의 `[협상가 제시 / 납품일 변경 도구 호출 절차 — 매우 중요]` 섹션 (라인 1636 근방, [정기배송 수정 요청] 직후, [자연어 → 카드 도구 안전장치] 직전). SELLER/BUYER 합성본 양쪽에 자동 반영. 6종 카드 도구 모두에 적용 (submit_counter_offer, submit_delivery_date_change, accept_counter_offer, reject_counter_offer, accept_delivery_date_change, reject_delivery_date_change).
  - **chat_node** 시스템 프롬프트의 동일 섹션 (라인 2849 근방, [자연어 협상/납품일 → 카드 도구 매핑] 직후). chat intent 라우팅 시 가장 자주 호출되는 노드라 BASE 와 별도로 박음.
  - **TOOLS schema** 의 `submit_counter_offer.order_id.description` + `submit_delivery_date_change.order_id.description` 보강. tool_call 인자 생성 직전 LLM 이 직접 읽는 위치에 "어떤 주문인지 모호하면 후보 추출 후 1개면 사용 / 2개+면 되묻기 / 0개면 안내" 절차 명시.
- 결정 트리 (3단계):
  - **[1단계 — 협상 가능 주문 목록 조회]** 협상가 제시는 `get_orders(status_in=['QUOTE_REQUESTED','NEGOTIATING'])`, 납품일 변경은 `status_in=['QUOTE_REQUESTED','NEGOTIATING','CONFIRMED']` 로 사전 필터링. CONFIRMED 이후(협상) / PREPARING 이후(납품일 변경) 차단되므로 사전 필터링 필수.
  - **[2단계 — 후보 필터링]** 사용자 발화 상품명 / 거래처 / 수량 매칭. 정확한 상품명, 동시에 수량 명시 시 수량도 매칭, 거래처 명시 시 거래처도 매칭.
  - **[3단계 — 후보 수에 따른 처리]**
    - 후보 0개: "○○ 상품에 대한 협상 가능한 주문이 없습니다 (이미 확정 이후 상태이거나 진행 중 주문 없음)" 안내만 하고 끝. 다른 주문 정보 늘어놓지 마라.
    - 후보 1개: 즉시 도구 호출 → 결과 안내.
    - 후보 2개 이상: "옥수수 50kg 주문(ORD-...) 과 옥수수 80kg 주문(ORD-...) 중 어느 주문에 협상가를 제시할까요?" 형식으로 되묻기. 답변 받기 전에는 절대 도구 호출 X.
- **발화 모호성 처리** (별도 강조): 사용자 발화가 어느 상품인지 너무 모호한 경우(예: "테스트 관리" 같은 비-상품 지시어) 임의로 한 주문을 추측 선택해 진행하지 말고 사용자에게 "어떤 상품의 주문에 대한 협상인가요?" 되묻기. 진행 중 주문 목록을 짧게 보여주는 것은 OK 지만 임의 선택 금지.
- **금지 사항 5종** (단정문 + 구체 anti-example):
  - 사용자가 안 물은 다른 주문 정보 줄줄이 나열.
  - 후보 여러 개일 때 임의 선택해서 진행.
  - 후보 0개일 때 다른 상품 주문 정보 끼워서 응답.
  - "주문 ID를 알려주세요"로 UUID 직접 요구.
  - accept/reject 도 동일 절차 적용 안 함 (수락/거절 PENDING 카드의 order_id 결정 시에도 동일한 결정 트리 따라야 함).
- 검증 결과: AST OK, placeholder 11/11 보존, BUYER/SELLER 합성본 모두 새 가이드 1회씩 포함 (`composition count = 1` 확인), chat_node 도 동일 가이드 포함, TOOLS schema 의 submit_counter_offer / submit_delivery_date_change order_id description 모두 갱신, BUYER 전용 가이드 (`주문 대상 판매자 식별 절차`, `구매자 주문/견적 생성 규칙`) SELLER 누출 0건, 이전 가이드 23종 모두 보존.
- **핵심 교훈 — 결정 트리는 매핑 가이드와 분리해서 독립 섹션으로 박아야 LLM 이 따라간다**: 자연어 → 도구 매핑 섹션 안에 "후보 여러 개면 되묻기" 가이드를 같이 박아두면 LLM 이 매핑 규칙만 보고 결정 트리는 무시한다. 결정 트리(0/1/N 분기)는 별도 섹션 + 각 단계에 헤더([1단계], [2단계], [3단계])를 박고 각 분기마다 구체 발화 예시까지 같이 넣어야 LLM 이 단계별로 검토한다. 매핑 가이드는 "어느 도구를 부르라"이고, 결정 트리는 "그 도구의 인자를 어떻게 정하라"이므로 관심사가 다름 → 분리가 자연스럽다.
- **핵심 교훈 — order_id 같은 UUID 인자는 schema description 에 결정 절차까지 박아야 LLM 준수율 최대화**: 본문 프롬프트만으로는 LLM 이 모호한 발화에서 임의로 한 후보를 선택하는 환각이 자주 발생. tool_call 인자 생성 직전에 LLM 이 다시 읽는 schema description 에 "0개/1개/2개+ 분기 + 임의 추측 금지" 절차를 박으면 schema 가 1차 방어선이 되고 본문 프롬프트가 보조한다. (이전 작업에서 검증된 패턴: seller_id 환각 차단 시에도 schema description 강화가 본문보다 효과 컸음. 이번 order_id 도 동일 패턴 적용.)
- **핵심 교훈 — 후보 0개 응답에서 "다른 주문 끼워 넣기" 환각이 가장 위험**: 후보 1개/2개+ 분기는 LLM 이 비교적 잘 따라가지만, 후보 0개일 때 GPT-4o-mini 가 "친절을 가장해" 컨텍스트 메모리의 다른 주문 정보를 줄줄이 노출하는 환각이 빈번. "○○ 상품에 대한 협상 가능한 주문이 없습니다" 만 짧게 답하고 끝내라는 단정문을 명시적으로 박아야 함. 이전 [도구 실패 시 응답 가이드] 의 "안 물은 정보 끌어오지 마라" 패턴과 동일 구조 — 환각 방지 가이드는 매번 명시적 단정문이 필요.

#### get_partners 자연어 → status 매핑 가이드 (2026-05-04 추가)
- 신규 `get_partners(user_id, status?, status_in?, role?)` 도구는 schema description 에 자연어 트리거("거래처 목록", "내 거래처", "거래 중인 곳" 등)와 ACTIVE/PENDING_OUTGOING/PENDING_INCOMING/INACTIVE 4종 enum 을 명시했지만, 본문 프롬프트에도 동일한 매핑을 박아야 LLM 이 일관되게 status 인자를 채운다. 이전 `get_orders` status_in 작업과 동일한 "schema + 본문 2중 명시" 패턴을 그대로 적용.
- 적용 위치 (orchestrator.py):
  - `AGENT_BASE_SYSTEM` 의 `[거래처 목록 조회 가이드 — 자연어 → status 매핑 (매우 중요)]` (라인 1753 근방, [주문 목록 조회 가이드] 직후, [주문 응답 표시 규칙] 직전). SELLER/BUYER 합성본 양쪽에 자동 반영.
  - `chat_node` 시스템 프롬프트의 동일 섹션 (라인 2940 근방, [주문 목록 조회 가이드] 직후, [주문 응답 표시 규칙 — 환각 방지 (매우 중요)] 직전). 사용자가 채팅 노드에서 "거래처 보여줘" 같이 자연어로 자주 묻는 위치라 BASE 와 별도로 박음.
- 자연어 매핑 핵심 (5종):
  1. "거래처 목록" / "내 거래처" / "거래 중인 곳" / "거래처 보여줘" / "거래하고 있는 거래처" / "내가 거래하는 사람들" → `status="ACTIVE"` (기본값)
  2. "보낸 거래처 신청" / "신청 보낸 곳" / "내가 신청한 거래처" / "보낸 요청" → `status="PENDING_OUTGOING"`
  3. "받은 거래처 신청" / "들어온 거래처 요청" / "거래처 신청 왔어?" → 단독 조회는 `get_incoming_partner_requests` 우선, 다른 상태와 함께 묻는 맥락에서만 `status="PENDING_INCOMING"`.
  4. "거절된 거래처" / "비활성 거래처" / "거래 종료된 곳" → `status="INACTIVE"`
  5. **상태 미명시** ("거래처 보여줘" / "거래처 목록") → 기본값 `status="ACTIVE"`.
- 응답 표시 규칙 핵심 (환각 방지 4종):
  - 0건이면 "현재 활성 거래처가 없습니다" (또는 status 에 맞춰 "보낸 거래처 신청이 없습니다" / "거절된 거래처가 없습니다") 만 안내. 다른 정보(주문 내역, 상품 추천, 다른 카테고리 거래처) 늘어놓지 말 것.
  - 도구가 반환하지 않은 거래처는 절대 응답에 포함 금지 — 컨텍스트 메모리/이전 대화의 옛 거래처 정보 출력 X.
  - 도구 결과 외 임의 정보 추가 금지. 사용자가 안 물은 다른 거래처 정보 카탈로그처럼 늘어놓지 말 것.
  - 마크다운 강조·표·헤더 금지. 자연체 한국어 + 필요 시 `1.` 번호.
- `get_orders` 와 차이점: `get_orders` 는 status_in 다중 enum 매핑이 핵심이라 8종 매핑을 본문에 박았지만, `get_partners` 는 사용자가 보통 한 번에 한 상태만 묻는 패턴이라 단일 status 매핑 5종이면 충분. status_in 은 "활성 거래처와 보낸 신청 둘 다" 같은 명시적 다중 요청에서만 사용한다는 단서를 본문에 박았다. PENDING_INCOMING 은 단독 조회 시 `get_incoming_partner_requests` 가 우선 — 도구 description 과 본문 가이드 모두에 동일하게 명시해 LLM 이 두 도구 중 어느 쪽을 부를지 헷갈리지 않게 함.
- 검증 결과: AST OK, placeholder 23/23 보존(이번 작업 23종 — 이전 11에서 변경 없음), BASE/chat_node 양쪽 1회씩 추가 확인, 이전 가이드 27종 모두 보존(`grep -c` 27 카운트), git diff --stat = 80 insertions(+) (단순 추가, 기존 줄 수정 0).
- **핵심 교훈 — 단일 enum 매핑도 schema 만 믿지 말고 본문에 한 번 더 박아야 일관성 확보**: `get_partners` schema description 에 이미 "거래처 목록", "내 거래처", "거래 중인 곳" 등 자연어 트리거가 명시돼 있어도, 사용자가 "보낸 신청" 같이 변형된 표현을 쓰면 LLM 이 status 인자를 누락하거나 status_in 으로 잘못 보내는 사례가 발생할 가능성이 있음. 본문 프롬프트의 5종 매핑이 backup 역할 — schema 가 1차, 본문이 2차 방어선. 단일 enum 도구도 다중 enum 도구와 동일하게 schema + 본문 2중 명시 패턴을 따라가는 것이 안전.
- **핵심 교훈 — 두 도구가 같은 의도(예: 받은 거래처 요청 조회)를 처리할 수 있을 때는 우선순위를 본문에 명시**: `get_partners(status="PENDING_INCOMING")` 와 `get_incoming_partner_requests` 가 둘 다 같은 데이터를 돌려주는 상황에서 LLM 이 둘 중 어느 쪽을 부를지 헷갈리면 같은 라운드에 두 도구를 동시 호출하거나 매번 다른 도구를 부르는 일관성 문제가 생긴다. "단독 조회 시엔 get_incoming_partner_requests 우선, 다른 상태와 함께 묻는 맥락에서만 get_partners(status='PENDING_INCOMING')" 처럼 우선순위 단서를 본문 + 도구 description 양쪽에 똑같이 박아야 LLM 이 일관되게 따라간다.

#### 거래처 목록 조회 가이드 보강 — 일반 발화 시 ACTIVE+PENDING 동시 조회 (2026-05-04 갱신)
- 배경: 직전 작업(라인 709 가이드)이 단일 status 매핑 중심이어서 사용자 일반 발화에 다음과 같은 환각이 재현됐다.
  - "현재 거래처 목록 알려줘" → AI 가 status="ACTIVE" 만 조회해 ACTIVE 1곳만 답하고 PENDING_OUTGOING / PENDING_INCOMING 보유 거래처를 누락.
  - "승인 대기중인 거래처가 있어?" → AI 가 어떤 도구도 호출하지 않고 "없습니다"라고 답함 (PENDING 동의어 매핑이 약해 발화-자체로 매핑이 끊어짐).
- 해결 — 두 가지 동시 적용:
  1. **일반 발화 기본값을 status_in 다중 조회로 전환**: "거래처 목록" / "내 거래처" / "거래처 보여줘" / "거래처 다 알려줘" / "거래처 현황" 처럼 사용자가 상태를 명시하지 않으면 `status_in=["ACTIVE","PENDING_OUTGOING","PENDING_INCOMING"]` 으로 한 번에 가져와 상태별로 분류해서 답한다. 직전 가이드의 "기본값 status='ACTIVE'" 정책을 명시적으로 폐기.
  2. **PENDING 동의어 사전 강화**: "승인 대기" / "신청 대기" / "기다리는 거래처" / "보낸 신청" / "내가 신청한 거" / "수락 대기" / "받은 신청" / "들어온 거래처 신청" 등 자연어 표현을 모두 PENDING_OUTGOING / PENDING_INCOMING 으로 직접 매핑. REJECTED("거절된 거래처") 와 INACTIVE("끊긴 거래처") 도 별도 분리해 정확도 ↑.
- 적용 위치 (orchestrator.py, 두 곳 동기):
  - `AGENT_BASE_SYSTEM` 의 `[거래처 목록 조회 가이드 — 매우 중요]` 섹션 (라인 441 부근). 큰따옴표 형식 (`status_in=["ACTIVE",...]`).
  - `chat_node` 시스템 프롬프트의 동일 섹션 (라인 1628 부근). 작은따옴표 형식 (`status_in=['ACTIVE',...]`). 자연어로 "거래처 보여줘" 가 채팅 노드에서도 자주 발생하므로 BASE 와 별도 동기화 유지.
- 응답 표현 규칙 (전체 조회 시):
  ```
  현재 거래처 현황입니다.
  - 거래 중: 판매자테스트(판매자) 1곳
  - 보낸 신청: 옥수수농장(이○○) 1곳 (수락 대기 중)
  - 받은 신청: 없음
  ```
  상태별 단독 조회는 그 상태만 답하고 다른 상태 정보를 끼워 넣지 말 것 (직전 가이드의 환각 방지 4종 그대로 유지).
- 검증 결과:
  - AST OK
  - placeholder 11/11 보존 (`role_label`, `role_label_short`, `case1/2/10/11_action`, `auth_product_rule`, `ambiguity_modify_rule`, `company_name`, `user_name`, `user_id`)
  - BASE/chat_node 양쪽 새 헤더 `[거래처 목록 조회 가이드 — 매우 중요]` 1회씩 (총 2 grep)
  - SELLER/BUYER 합성본 둘 다 새 가이드 1회씩 포함, 잔여 placeholder 0
  - BUYER 전용 가이드(`주문 대상 판매자 식별 절차`, `🚨 구매자 주문/견적 생성 규칙`) SELLER 누출 0건, SELLER 전용 가이드(`거래 끊긴 곳 대신할 구매자`, `신규 바이어 발굴`) BUYER 누출 0건
  - 옛 가이드 표현(`자연어 → status 매핑`, `단일 상태 파라미터로 정확히 매핑`, `status 단일을 우선`) grep 0건 = 정확히 제거됨
  - 이전 가이드 10종(핵심 대화 원칙, 대체 거래처, send_chat_message needs_confirmation, 자연어→카드, 협상가/납품일 절차, 안전장치, 재고 vs 대체, 주문 목록 status_in, 주문 응답 표시, 도구 실패 환각 방지) 모두 보존
  - git diff --stat = 1 file changed, 40 insertions(+), 21 deletions(-)
- **핵심 교훈 — 사용자 일반 발화의 기본값은 "정확히 한 상태"가 아니라 "사용자가 보고 싶을 만한 모든 상태의 묶음"이어야 한다**: 거래처는 사용자가 자연스럽게 "내 거래처 다 보여줘"라고 했을 때 ACTIVE 1곳만 보여주면 진행 중인 거래처 신청을 빼먹은 것으로 오인된다. 일반 발화에서는 status_in 다중 조회를 기본으로 두고, 사용자가 명시적으로 한 상태를 콕 집어 묻는 경우(예: "거래 중인 곳만") 만 단일 status 로 좁힌다. 직전 작업의 "단일 status 5종 매핑"은 정확하지만 "기본값 ACTIVE" 부분이 사용자 멘탈 모델과 불일치 — 다중 조회를 기본값으로 바꿔야 사용자가 만족.
- **핵심 교훈 — PENDING 동의어 사전은 명시적으로 길게 박아야 LLM 이 일관되게 매핑한다**: "승인 대기", "신청 대기", "기다리는 거래처", "수락 대기" 같은 동의어가 가이드 본문에 명시 안 돼 있으면 LLM 이 "PENDING 상태에 대한 도구 호출"을 스킵하고 "없다"고 환각으로 답한다. 동의어 사전을 길게 펼쳐 박는 것이 5종 enum 만 박는 것보다 실전 발화 커버리지가 훨씬 높다.

#### 정기배송 목록 조회 가이드 신설 — get_subscriptions 자연어 매핑 + 거래처 교차 조회 (2026-05-04 추가)
- 배경: backend-agent 가 `get_subscriptions` 도구를 신설(`backend/app/services/agent/tools/subscription.py`). description 에 자연어 트리거가 명시돼 있지만, BUYER/SELLER 가이드 본문에 자연어 → 호출 매핑이 없어 LLM 이 단일 status 만 부르거나 PENDING 상태를 누락하는 환각 가능성이 있었다. 거래처 가이드와 동일한 보강 패턴(일반 발화는 status_in 다중, 특정 상태는 단일 status)을 정기배송에도 적용.
- 해결 — 두 가지 동시 적용:
  1. **일반 발화 기본값을 status_in 다중 조회로 전환**: "정기배송 목록" / "내 정기배송" / "정기배송 보여줘" / "정기배송 현황" 처럼 사용자가 상태를 명시하지 않으면 `status_in=["ACTIVE","PENDING_OUTGOING","PENDING_INCOMING"]` 으로 한 번에 가져와 "진행 중 N건, 보낸 신청 N건, 받은 신청 N건" 으로 분류해서 답한다.
  2. **거래처 + 정기배송 교차 조회 절차 명시**: "거래처 중 정기배송 있는 곳" / "거래 중인 곳 정기배송" 같이 두 도메인을 동시에 묻는 발화 패턴을 직접 매핑 — 먼저 `get_partners(status="ACTIVE")` 로 활성 거래처 확인 → `get_subscriptions(status="ACTIVE")` 로 진행 중 정기배송 → 두 결과를 교차해 답변. 활성 거래처 0곳이면 "활성 거래처가 없어 정기배송 조회 불가" 안내.
  3. **상태별 단독 조회 7종 매핑**: ACTIVE("진행 중인 정기배송"), PENDING_OUTGOING("보낸 정기배송 신청"), PENDING_INCOMING("받은 정기배송 신청" — 단독은 `get_incoming_subscription_requests` 우선), PAUSED("일시정지", "쉬고 있는"), ENDED("종료된", "끝난"), REJECTED("거절된"), CANCELLED("취소된").
- 적용 위치 (orchestrator.py, 두 곳 동기 — 이전 거래처 가이드와 동일 5중 명시 패턴):
  - `AGENT_BASE_SYSTEM` 의 `[정기배송 목록 조회 가이드 — 매우 중요]` 섹션 (라인 473 근방, [거래처 목록 조회 가이드] 직후, [주문 응답 표시 규칙] 직전). SELLER/BUYER 합성본 양쪽에 자동 반영. 큰따옴표 형식.
  - `chat_node` 시스템 프롬프트의 동일 섹션 (라인 1694 근방, [거래처 목록 조회 가이드] 직후, [주문 응답 표시 규칙 — 환각 방지] 직전). 작은따옴표 형식. 자연어로 "정기배송 보여줘" 가 채팅 노드에서도 자주 발생하므로 BASE 와 별도 동기화 유지.
- 응답 표현 규칙 (전체 조회 시 — 거래처 가이드와 같은 형식):
  ```
  정기배송 현황입니다.
  - 진행 중 (ACTIVE): A마트 매주 옥수수 50kg 외 2종 (다음 예정 5월 10일)
  - 보낸 신청 (PENDING_OUTGOING): B농가 격주 사과 30kg (수락 대기)
  - 받은 신청 (PENDING_INCOMING): 없음
  ```
  각 항목은 상대방 회사명/담당자, frequency 한글(WEEKLY→"매주", BIWEEKLY→"격주", MONTHLY→"매월"), start_date, 다음 예정일, 품목 요약을 자연체로 풀어 안내. 상태별 단독 조회는 그 상태만 답하고 다른 상태 정보를 끼워 넣지 말 것 (이전 가이드의 환각 방지 4종 그대로 유지).
- 검증 결과:
  - AST OK (`python3 -m ast` parse 성공)
  - placeholder 11/11 보존 (`role_label: 3, company_name: 6, user_name: 6, user_id: 27→49 (BASE +9 / chat_node +13), role_label_short: 1, case1/2/10/11_action: 각 1, auth_product_rule: 2, ambiguity_modify_rule: 2`)
  - `_build_role_system(AGENT_BASE_SYSTEM, _SELLER_ROLE_VARS)` 렌더 OK (잔여 placeholder 0, len 18792)
  - `_build_role_system(AGENT_BASE_SYSTEM, _BUYER_ROLE_VARS)` 렌더 OK (잔여 placeholder 0, len 18756)
  - BASE/chat_node 양쪽 새 헤더 `[정기배송 목록 조회 가이드 — 매우 중요]` 1회씩 (총 2 grep)
  - 이전 가이드 18종(가독성, 대체 거래처, send_chat_message needs_confirmation, 자연어→카드, 협상가/납품일 절차, 안전장치, 재고 vs 대체, 거래처 등록, 정기배송 등록, 주문 후 채팅방 연결, auto_confirm/납품일 필수, seller_id 1순위, 도구 실패 환각 방지, 주문 목록 status_in, 주문 응답 표시, 거래처 목록 조회, 협상가/납품일 order_id 결정, find_alternative_partners) 모두 보존
  - git diff --stat = 1 file changed, 53 insertions(+), 0 deletions(-)
- **핵심 교훈 — 도메인 교차 조회는 본문에 절차를 명시해야 LLM 이 두 번 호출한다**: "거래처 중 정기배송 있는 곳" 같은 두 도메인 동시 질문은 LLM 에게 자연스럽게 "한 번의 도구 호출"로 풀려는 경향이 있다. 본문에 "먼저 get_partners 로 활성 거래처 확인 → get_subscriptions 로 진행 중 정기배송 → 두 결과 교차" 라는 2단계 절차를 명시적으로 박아야 LLM 이 일관되게 두 번 호출하고 교차 결과를 만든다. 단일 도구 호출만 하고 한 도메인 정보를 누락하는 환각을 차단하는 것이 핵심.
- **핵심 교훈 — 일반 발화 기본값 = status_in 다중 패턴은 도메인 무관한 표준 패턴**: 거래처 / 주문 / 정기배송 모두 사용자가 "○○ 보여줘" 라고 말할 때 ACTIVE 만 답하면 PENDING/진행 중 항목을 누락한 것으로 인식된다. 도메인이 늘어날 때마다 (1) 일반 발화 기본값 = status_in 다중, (2) 상태별 단독 조회 = 단일 status, (3) 동의어 사전 명시 — 이 3종 세트를 표준으로 박아 두는 것이 LLM 일관성에 가장 효과적이다. 향후 새 list 도구(예: 캘린더 일정, 알림) 추가 시도 동일 패턴 따르기.

#### 정기배송 가이드 보강 — 거래처+정기배송 교차 조회에 PAUSED 포함 (2026-05-04 추가, 테스터 피드백)
- 배경: 직전 b48bf64 의 [정기배송 목록 조회 가이드] 에서 "거래처 + 정기배송 교차 조회" 절차는 `get_partners(ACTIVE) + get_subscriptions(ACTIVE)` 만 보고 두 결과를 교차하도록 명시했다. 하지만 테스터 환경에서 활성 거래처가 1곳(판매자테스트)이고 그 거래처와의 정기배송이 PAUSED 상태로 존재하는 케이스가 있었는데, AI 가 ACTIVE 만 보고 "현재 진행 중인 정기배송은 없어요" 라고 답해 PAUSED 정기배송을 통째로 누락하는 사고가 발생.
- 진단 — "정기배송이 있는 곳" 의 의미 확장: 사용자 일반 발화 "거래처 중 정기배송 있는 곳" 의 멘탈 모델에는 ACTIVE 뿐 아니라 PAUSED(잠시 멈춤) / PENDING_OUTGOING(보낸 신청) / PENDING_INCOMING(받은 신청) 까지 "있는 곳" 으로 인지된다. ACTIVE 만 답하면 PAUSED 케이스가 통째로 빠진다. 명시적으로 "진행 중", "활성" 을 강조한 발화에 한해서만 ACTIVE 단독.
- 해결 — 두 곳 동기화 (BASE/chat_node):
  1. **교차 조회 절차의 두 번째 호출 변경**: `get_subscriptions(status="ACTIVE")` → `get_subscriptions(status_in=["ACTIVE","PAUSED","PENDING_OUTGOING","PENDING_INCOMING"])` (살아있는 정기배송 모두). 응답은 "○○ 거래처와 정기배송 N건 (ACTIVE 1, PAUSED 1)" 형식으로 상태별 분류 포함.
  2. **명시적 ACTIVE 강조 분기 추가**: "거래처 중 진행 중인 정기배송", "지금 활성으로 받고 있는 정기배송 거래처" 처럼 ACTIVE 를 명시한 발화에서만 `status="ACTIVE"` 단독 사용.
  3. **응답 표현 예시 추가 (ACTIVE/PAUSED 혼합)**: "○○ 거래처와 진행 중인 정기배송 1건, 일시정지된 정기배송 1건 (총 2건) - 진행 중: 매주 옥수수 50kg(다음 5월 10일) - 일시정지: 격주 사과 30kg(재개 시 다시 안내)".
- 적용 위치 (orchestrator.py):
  - `AGENT_BASE_SYSTEM` 의 `[정기배송 목록 조회 가이드 — 매우 중요]` 안 "(거래처 + 정기배송 교차 조회 — 매우 중요)" 블록 (라인 482-487 부근). 큰따옴표 형식. 응답 표현 예시는 `[응답 표현 규칙]` 안 (라인 504-507 부근) "분류 표현 예시" 직후에 추가.
  - `chat_node` 시스템 프롬프트의 동일 섹션 (라인 1703 부근, 큰따옴표→작은따옴표 차이만). 응답 표현 규칙은 (라인 1715 부근) 한 줄 주석으로 인라인 추가.
- 검증 결과:
  - AST OK (`python3 -c "import ast; ast.parse(...)"` 통과)
  - placeholder 보존 — `{user_id}` 43→44 (교차 조회 절차에 호출 단계 명시 1줄 늘면서 자연 증가), `{company_name}` 6→6, `{user_name}` 6→6
  - BASE/chat_node 양쪽 매핑 동기화 (`status_in=['ACTIVE','PAUSED','PENDING_OUTGOING','PENDING_INCOMING']` grep 시 BASE 1회 + chat_node 1회 = 2회)
  - 이전 가이드 18+종(가독성, 대체 거래처, send_chat_message needs_confirmation, 자연어→카드, 협상가/납품일 절차, 안전장치, 재고 vs 대체, 거래처 등록, 정기배송 등록, 주문 후 채팅방 연결, auto_confirm/납품일 필수, seller_id 1순위, 도구 실패 환각 방지, 주문 목록 status_in, 주문 응답 표시, 거래처 목록 조회, 협상가/납품일 order_id 결정, find_alternative_partners, 정기배송 목록 조회) 모두 보존
  - git diff --stat = 1 file changed, 9 insertions(+), 3 deletions(-)
- **핵심 교훈 — "있는 곳" 같은 자연어 표현의 멘탈 모델은 LLM 의 단순 enum 매핑보다 넓다**: 사용자가 "정기배송 있는 곳" 이라고 할 때 머릿속에는 진행 중 + 일시정지 + 신청 대기 모두가 "있다" 로 포함된다. LLM 이 "있다 = ACTIVE" 로 좁히면 PAUSED 케이스가 통째로 사라진다. 교차 조회 가이드는 단순히 "두 도구를 호출하라" 가 아니라 "각 도구를 어떤 status_in 으로 호출할지" 까지 박아야 멘탈 모델 불일치에 의한 환각을 막을 수 있다. 명시적 강조("진행 중인", "활성")가 있을 때만 좁히는 분기를 함께 두는 것이 핵심.
- **핵심 교훈 — 라이브 데이터 기반 실측 케이스가 가이드 보강의 출발점**: 기능 출시 시점에 ACTIVE 하나만 매핑한 게 "최소 동작 가능"이었지만, 테스터 환경에서 PAUSED 정기배송이 실제로 존재하는데 누락된 응답이 나오면 즉시 신뢰가 깨진다. 도메인 가이드는 한 번 박은 뒤 라이브 데이터로 한 번 검증하는 사이클이 필수 — schema 의 enum 만 보고 "이 정도면 되겠지" 라고 가이드를 짜면 사용자 멘탈 모델과 어긋난 매핑을 못 잡아낸다.

#### 도구 모듈화 리팩터링 — PR 0 인프라 신설 (2026-05-04 추가)
- 배경: `backend/app/services/agent_tools.py` 가 41개 도구를 한 파일(약 16만 자)에 담고 있어 LLM·휴먼 모두 한 도구를 수정할 때 다른 도구의 컨텍스트를 끌고 가야 하는 구조. 도구 추가/수정 시 회귀 위험과 머지 충돌이 누적되는 패턴을 격리하기 위해 도메인별 분리 진행. 사용자 승인된 설계 = "단계별 PR 으로 점진 이동, PR 0 은 인프라만 — 회귀 위험 0".
- PR 0 신설 파일 (5개, 절대 경로):
  - `backend/app/services/agent/__init__.py` (30 lines) — 외부 공개 API. `TOOL_FUNCTION_MAP` / `TOOLS` / `TOOLS_CALENDAR` / `TOOLS_CHAT` / `INT_FIELDS` 5심볼만 export. 등록 트리거를 위해 `from . import tools` 가 첫 줄.
  - `backend/app/services/agent/_registry.py` (104 lines) — `ToolEntry` (frozen dataclass: name/func/schema/groups/int_fields), `ToolRegistry` (글로벌 dict 기반, register/function_map/schemas_for/int_fields_union/all_entries 5메서드), `tool(...)` 데코레이터.
  - `backend/app/services/agent/_shared.py` (10 lines) — cross-domain helper placeholder. PR 0 에서는 비어있고, 다음 PR 들에서 `_run_async_in_thread` 등 이동 예정.
  - `backend/app/services/agent/tools/__init__.py` (20 lines) — 도메인 모듈 import 트리거. PR 0 에서는 모든 import 가 주석 처리 (도메인 모듈 0개).
  - `backend/tests/test_agent_registry.py` (106 lines) — pytest 7개 케이스: register/lookup, 중복 RuntimeError, 미존재 그룹 빈 list, int_fields union, 빈 groups ValueError, list 타입 groups ValueError, multi-group 등록.
- PR 0 의 핵심 가치 — **회귀 위험 0**: `agent_tools.py` / `orchestrator.py` / `chat_ws.py` 일절 수정 X. 기존 `from app.services.agent_tools import TOOL_FUNCTION_MAP` (orchestrator.py 라인 39) 그대로 동작. 새 `app.services.agent` 패키지는 import 만 가능하고 0개 도구만 노출 — 다음 PR 들에서 도메인 모듈을 점진적으로 옮긴 뒤 마지막 PR 에서 orchestrator import 경로를 한 줄 바꿈.
- 검증 결과 — 5종 모두 통과:
  1. AST 파싱: 5개 파일 모두 OK.
  2. import 동작: `python -c "from app.services.agent import TOOL_FUNCTION_MAP, ..."` → `OK 0 tools registered` (PR 0 에서는 도구 0개로 정상).
  3. 단위 테스트: `pytest tests/test_agent_registry.py --noconftest -v` → 7 passed in 0.01s. (`--noconftest` 는 기존 `tests/conftest.py` 가 httpx 등 외부 의존성 import 하는 문제 회피용 — 신규 인프라 테스트는 외부 의존성 없음.)
  4. 기존 import 경로 보존: orchestrator.py 의 `from app.services.agent_tools import TOOL_FUNCTION_MAP` regex 로 존재 확인.
  5. git diff --stat HEAD = 비어있음 (modifications 0개, 신규 untracked 만 5개).
- 데코레이터 사용 패턴 (다음 PR 에서 적용):
  ```python
  # tools/product.py 예시
  from .._registry import tool

  @tool(
      name="get_products",
      description="...",
      parameters={"type": "object", "properties": {...}, "required": [...]},
      groups=("inventory_order",),
      int_fields=frozenset({"min_stock", "max_stock"}),
  )
  def get_products(seller_id: str, ...) -> dict:
      ...
  ```
  - 도구 본문 + schema 가 한 hunk 에 묶여 격리 — 한 도구 수정 시 다른 도구 컨텍스트 불필요.
  - groups 는 비어있지 않은 tuple 강제. `groups=("inventory_order",)` 처럼 trailing comma 필수 (단일 그룹도 tuple 보장).
  - `int_fields` 는 LLM 이 string 으로 보내는 인자를 자동 int 변환할 필드 — `@tool` 등록 시 도구별 int 변환 정책이 함수 정의와 같은 위치에 박혀 가독성 향상.
- 다음 PR 계획 (도메인별 분리 — 8개 PR, 각 PR 회귀 영향 격리):
  - PR 1: product (6개) — get_products / find_sellers_by_product / find_buyers_by_product / 등.
  - PR 2: order (6개) — get_orders / create_order / update_order / update_order_status / delete_order / cancel_order.
  - PR 3: chat (4개) — chat_send_message / chat_create_room / 등.
  - PR 4: calendar (4개).
  - PR 5: partner (7개).
  - PR 6: subscription (4개).
  - PR 7: negotiation (6개) — submit_counter_offer / accept_counter_offer / reject_counter_offer / submit_delivery_date_change / 등.
  - PR 8: user (3개) — orchestrator import 경로를 `from app.services.agent import ...` 으로 한 줄 변경 + `agent_tools.py` 빈 shim 또는 삭제.
- **핵심 교훈 — 인프라 PR 은 "회귀 0 보장" 자체가 핵심 가치**: 큰 리팩터링은 1단계 인프라 PR + N단계 점진 이동 PR 로 분리하면 각 단계마다 회귀 영향이 독립적으로 검증 가능. PR 0 의 인프라가 0개 도구만 노출하더라도 unit test 7종으로 인프라 자체의 정합성을 검증해두면 다음 PR 들에서 도메인 모듈을 추가할 때마다 test_agent_registry 가 회귀 sentinel 역할을 한다.
- **핵심 교훈 — 새 패키지의 `__init__.py` 첫 줄에 `from . import tools  # noqa: F401`**: 데코레이터 기반 등록 시스템은 모듈 import 가 곧 등록 트리거이므로, 외부에서 `from app.services.agent import TOOL_FUNCTION_MAP` 만 호출해도 자동으로 모든 도메인 모듈이 import 되어야 한다. 패키지 `__init__.py` 첫 줄에 명시적으로 `from . import tools` 를 박고, `tools/__init__.py` 에서 모든 도메인 모듈을 명시 import. 이렇게 하면 외부 호출자는 import 순서를 신경 쓸 필요 없이 자동으로 등록이 완료된 상태의 registry 를 받는다.
- **핵심 교훈 — `--noconftest` 로 인프라 단위 테스트를 외부 의존성 없이 실행**: 기존 `backend/tests/conftest.py` 는 httpx/Supabase 등 외부 패키지 import 가 있어 venv 미설치 환경에서 collect 단계에서 실패한다. 인프라 단위 테스트(`test_agent_registry.py`) 는 자체 import 가 stdlib + pytest 만 사용하므로 `pytest --noconftest` 로 conftest 우회 실행하면 venv 없이도 7케이스 모두 통과. 다음 PR 들의 도메인 모듈 단위 테스트도 동일 패턴(외부 의존성 mock 또는 회피)으로 작성하면 venv 없이 검증 가능.

#### 도구 모듈화 리팩터링 — PR 1 단계 1: 6개 도메인 모듈 신설 (2026-05-04 완료)
- 단계 1 의 핵심 가치 — **회귀 0 보장 (PR 0 와 동일 원칙)**: `agent_tools.py` / `orchestrator.py` 일절 수정 X (`git diff` 0 lines). 새 도메인 모듈에 `@tool` 데코레이터로 도구를 복제 등록만 하고, 단계 2 에서 agent_tools.py 를 shim 으로 변환 + orchestrator import 경로 교체 예정.
- 신설 6개 모듈 (절대 경로, 도구 수, 라인 수):
  - `backend/app/services/agent/tools/product.py` (604 lines, 6 도구) — get_products, check_stock, update_stock, create_product, delete_product, update_product. 도메인 helper `_find_product_by_name` 포함 (order/subscription 모듈에서 lazy import 로 재사용).
  - `backend/app/services/agent/tools/order.py` (861 lines, 6 도구) — get_orders, get_order_detail, update_order_status, update_order, create_order, delete_order. `_sync_calendar_events_for_order_id` / `_run_async_in_thread` / `_service_error_payload` / `_find_seller_by_name` / `_deduct_seller_stock_for_order` 는 agent_tools.py 에서 lazy import (단계 2 에서 _shared.py 로 이동 예정).
  - `backend/app/services/agent/tools/partner.py` (900 lines, 7 도구) — find_alternative_partners, request_partner_registration, request_partner_registration_by_name, get_partners, get_incoming_partner_requests, accept_partner_request, reject_partner_request. 도메인 helper `_build_partner_response` 포함.
  - `backend/app/services/agent/tools/subscription.py` (796 lines, 4 도구) — create_subscription_request, accept_subscription_request, reject_subscription_request, create_subscription_from_order. 도메인 helper `_normalize_frequency` / `_normalize_iso_date` / `_resolve_subscription_items` 포함. (`get_incoming_subscription_requests` 는 다음 PR 에서 추가.)
  - `backend/app/services/agent/tools/negotiation.py` (548 lines, 6 도구) — submit/accept/reject_counter_offer + submit/accept/reject_delivery_date_change. 모든 도구가 동기 sync 래퍼로 `order_service` async 메서드를 `_run_async_in_thread` 통해 호출.
  - `backend/app/services/agent/tools/user.py` (452 lines, 4 도구) — get_user_profile, find_sellers_by_product, find_buyers_by_product, open_chat_room. (사용자/판매자/구매자 탐색 도구는 user 도메인에 묶었음.)
- `backend/app/services/agent/tools/__init__.py` 갱신 — 6 모듈 import 추가, calendar/chat/get_incoming_subscription_requests 는 PR 2/3 예약.
- 검증 결과 — 5종 모두 통과:
  1. AST 파싱: 6개 신규 모듈 모두 OK.
  2. import 동작: `from app.services.agent import TOOL_FUNCTION_MAP` → 33개 도구 등록 (TOOLS schemas 33, TOOLS_CALENDAR 0, TOOLS_CHAT 0). 6+6+7+4+6+4 = 33 정확히 일치.
  3. 단위 테스트: `pytest tests/test_agent_registry.py --noconftest -v` → 9 passed (기존 7 + 신규 2: `test_domain_modules_register_33_tools` + `test_domain_modules_int_fields_union`).
  4. agent_tools.py 공존: `agent_tools.TOOL_FUNCTION_MAP` 41개 + `agent.TOOL_FUNCTION_MAP` 33개 동시 import 시 RuntimeError 미발생 — `@tool` 데코레이터가 도메인 모듈에만 있고 agent_tools.py 에는 없어 같은 이름 등록 충돌 없음.
  5. 회귀 0: orchestrator.TOOLS 35 (변경 없음, 35 = PR 1 33 + 단계 2 미도착 2: `get_incoming_subscription_requests` + `send_chat_message`), TOOLS_CALENDAR 4, TOOLS_CHAT 3 모두 변경 없음.
- **핵심 교훈 — cross-domain helper 는 단계 1 에서 lazy import 로 충분**: `_run_async_in_thread`, `_service_error_payload`, `_UUID_PATTERN`, `_sync_calendar_events_for_order_id` 등은 agent_tools.py top-level 에 있고 단계 2 에서 `_shared.py` 로 이동 예정. 단계 1 에서는 도메인 모듈 함수 본문 안쪽에서 `from app.services.agent_tools import _run_async_in_thread` 형태로 lazy import — 모듈 top-level import 보다 코드 가독성이 떨어지지만 **순환 import 위험을 회피**하고 단계 2 에서 한꺼번에 정리 가능. 도메인 helper (`_find_product_by_name`, `_build_partner_response`, `_normalize_frequency` 등) 는 처음부터 도메인 모듈 안에 직접 둠.
- **핵심 교훈 — 같은 이름 함수가 두 곳에 살아도 ToolRegistry 중복 안 터지는 이유**: `agent_tools.py` 의 33 함수는 `TOOL_FUNCTION_MAP` 딕셔너리에만 등록되어 있고 `@tool` 데코레이터가 없다. 새 `app/services/agent/tools/*.py` 의 함수들만 `@tool` 데코레이터로 `ToolRegistry._items` 에 등록되므로 한 이름당 등록 1회만 발생 → 단계 1 에서 같은 함수가 두 파일에 동시 존재해도 RuntimeError("ToolRegistry 중복 등록") 발생 안 함. 단계 2 에서 agent_tools.py 의 함수 본문을 `from .agent.tools.product import get_products` 형태의 shim 으로 변환할 때 그제서야 두 곳에서 같은 함수 객체를 참조하게 되어 중복 우려가 사라짐.
- **검증된 lazy import 패턴 (단계 1 단점 회피용)**: 모듈 top-level 에서 `from app.services.agent_tools import ...` 하면 agent_tools.py 가 로드되며 그 안에서 `from app.services.order_service import order_service` 등이 chain reaction 으로 실행될 수 있다. 단계 1 에서는 함수 안쪽에 lazy import 두면 첫 호출 시점까지 import 지연 → 다른 도구가 같은 helper 를 호출해도 Python 의 module cache 가 한 번만 import 보장.
- 단계 2 (다음 PR) 작업 범위:
  1. agent_tools.py 의 33 함수를 `from .agent.tools.{domain} import {fn_name}` 형태의 shim 으로 변환.
  2. `_shared.py` 에 cross-domain helper (`_run_async_in_thread`, `_service_error_payload`, `_UUID_PATTERN`) 이동 + agent_tools.py 의 동일 helper 는 re-export shim.
  3. orchestrator.py 의 `from app.services.agent_tools import TOOL_FUNCTION_MAP, TOOLS, ...` 를 `from app.services.agent import ...` 로 교체.
  4. 잔여 도구(get_incoming_subscription_requests, send_chat_message, calendar 4종, chat 2종) 는 PR 2/3 별도 처리.

#### 도구 모듈화 리팩터링 — PR 1 단계 2: shim 변환 + orchestrator TOOLS 정리 (2026-05-04 완료)
- 단계 2 의 핵심 가치 — **회귀 0 + 코드 -4255 줄**: `agent_tools.py` (4052 → 1310, -2742 줄) + `orchestrator.py` (3467 → 2302, -1165 줄). 단계 1 에서 도메인 모듈에 복제만 했던 33 도구의 본문이 이제 단일 정의 위치(`agent/tools/{domain}.py`) 만 남고, `agent_tools.py` 는 외부 호환을 위한 re-export shim 으로 축소.
- agent_tools.py 변경 (1310 줄 — 약 70% 축소):
  - 옮긴 33 도구 함수의 **본문 제거** + `from app.services.agent.tools.{domain} import ...` 형태로 re-export. `from app.services.agent_tools import get_products` 같은 옛 import 가 그대로 동작 (function identity 보존: `agent_tools.get_products IS agent.tools.product.get_products`).
  - 잔존 8 도구 본문 유지: `get_chat_rooms`/`get_chat_messages`/`send_chat_message` (chat 3, PR 3 이동 예정), `get_calendar_events`/`create_calendar_event`/`update_calendar_event`/`delete_calendar_event` (calendar 4, PR 2 이동 예정), `get_incoming_subscription_requests` (subscription 1, PR 2/3 이동 예정).
  - cross-domain helper 본문 유지 (PR 4 에서 `_shared.py` 로 이동 예정): `_UUID_PATTERN`, `_sync_calendar_events_for_order_id`, `_find_seller_by_name`, `_find_product_by_name`, `_run_async_in_thread`, `_service_error_payload`, `_deduct_seller_stock_for_order`. + `_resolve_chat_room_candidates`, `_do_send_chat_message` (chat 도구 내부 helper).
  - `analyze_chat_consensus` + `CONSENSUS_SYSTEM_PROMPT` + `_CONSENSUS_FALLBACK` 유지 (chat_ws.py 가 직접 import; TOOL_FUNCTION_MAP 미등록).
  - **TOOL_FUNCTION_MAP 머지**: `from app.services.agent import TOOL_FUNCTION_MAP as _REGISTRY_MAP` + 잔존 8 항목 직접 추가 = **41개** (33 + 8). 외부 코드 (`from app.services.agent_tools import TOOL_FUNCTION_MAP`) 는 그대로 41개 받음.
  - 추가 re-export: `TOOLS`, `TOOLS_CALENDAR`, `TOOLS_CHAT`, `INT_FIELDS` 도 registry 에서 재노출 (옛 import 호환). 단계 2 시점 값 = TOOLS:33 / TOOLS_CALENDAR:0 / TOOLS_CHAT:0 (calendar/chat registry 등록은 PR 2/3).
- orchestrator.py 변경 (2302 줄 — 약 33% 축소):
  - line 73-1316 의 **`TOOLS = [...]` 리터럴 (1244 줄, 35 schema)** 제거 → registry 기반 합성으로 교체:
    ```python
    from app.services.agent import TOOLS as _REGISTRY_INVENTORY_ORDER_TOOLS
    TOOLS = list(_REGISTRY_INVENTORY_ORDER_TOOLS) + [<send_chat_message_schema>, <get_incoming_subscription_requests_schema>]
    ```
    33 schema 는 `@tool` 데코레이터가 자동 노출, 잔존 2 schema (`send_chat_message`, `get_incoming_subscription_requests`) 는 도메인 모듈로 이동될 때까지 직접 보유 → LLM 회귀 0.
  - `TOOLS_CALENDAR` (line 287, 4개), `TOOLS_CHAT` (line 363, 3개) 는 **그대로 유지** — calendar_data_node / chat_node 가 직접 사용. PR 2/3 에서 도메인 모듈 신설 시 registry 기반으로 교체 예정.
  - `_execute_tool` 내부의 inline `INT_FIELDS = {...}` set (line 947) 도 그대로 유지 — 일관성을 위해 PR 4 에서 `agent.INT_FIELDS` 로 통합 예정.
- 검증 (모두 PASSED):
  1. `pytest tests/test_agent_registry.py` — 9/9 통과.
  2. agent_tools 호환 import: `from app.services.agent_tools import TOOL_FUNCTION_MAP, TOOLS, TOOLS_CALENDAR, TOOLS_CHAT, get_products, ..., _UUID_PATTERN, _sync_calendar_events_for_order_id, analyze_chat_consensus` 41 / 33 / 0 / 0 모두 정상.
  3. orchestrator 호환 import: `from app.services import orchestrator` → TOOLS:35 / TOOLS_CALENDAR:4 / TOOLS_CHAT:3 / TOOL_FUNCTION_MAP:41.
  4. chat_ws 호환 import: `from app.websocket import chat_ws` → 정상 (analyze_chat_consensus, _sync_calendar_events_for_order_id, find_alternative_partners, get_chat_rooms 모두 정상 import).
  5. function identity: `agent_tools.get_products is agent.tools.product.get_products` → True (re-export 가 같은 함수 객체).
  6. FastAPI app boot: `from app.main import app` → 70 routes 정상 로드.
- **검증된 패턴 — Option C (TOOL_FUNCTION_MAP 머지)**: `agent_tools.py` 의 `TOOL_FUNCTION_MAP` 을 완전히 제거하면 잔존 8 도구의 호출 경로가 끊긴다 (LLM 이 `send_chat_message` 를 부르려 하면 `KeyError`). 해결 = registry map (33) 과 잔존 8 항목을 한 dict 로 머지해 노출. orchestrator 의 `from app.services.agent_tools import TOOL_FUNCTION_MAP` 는 그대로 동작하며 41 항목 모두 호출 가능.
- **검증된 패턴 — `list(_REGISTRY_TOOLS)` 사본 합성**: `TOOLS = _REGISTRY_TOOLS + [<leftover>]` 는 registry 의 내부 list 를 직접 변형할 위험이 있다 (앞으로 다른 PR 에서 `TOOLS_CALENDAR.append(...)` 같은 코드가 나오면 즉시 폭발). `list(_REGISTRY_TOOLS)` 로 얕은 복사한 뒤 `+ [<leftover>]` 로 합성하면 registry 는 immutable 유지. 동일 패턴 권장 — `list(...) + [...]` 합성.
- **검증된 함정 — circular import 위험 (회피됨)**: `agent_tools.py` 가 `app.services.agent` 를 import 하고, `agent.tools.{domain}.py` 가 lazy import 로 `agent_tools._UUID_PATTERN` 을 가져온다. 이 두 방향이 합쳐져 circular 가 될 위험이 있지만, **lazy import 가 함수 본문 안쪽에 있어 첫 호출 시점까지 지연** 되므로 import 시점에는 cycle 이 닫히지 않는다. agent_tools.py 의 top-level 에서 `from app.services.agent import TOOL_FUNCTION_MAP as _REGISTRY_MAP` 가 실행될 때, agent 패키지의 `tools/__init__.py` 가 도메인 모듈을 import 하는 시점에는 함수 호출이 일어나지 않으므로 안전.
- 단계 3 (PR 2/3 — chat / calendar 도메인 모듈 신설):
  - PR 2 (완료, 2026-05-04) — calendar 도메인 모듈 신설 (4 도구). agent_tools.py 의 `get_calendar_events`/`create_calendar_event`/`update_calendar_event`/`delete_calendar_event` 본문 → `agent/tools/calendar.py` 로 이동 + `@tool(groups=("calendar",))` 등록. orchestrator.py 의 `TOOLS_CALENDAR` 리터럴 → `from app.services.agent import TOOLS_CALENDAR` 로 교체.
  - PR 3 (완료, 2026-05-04) — chat 도메인 모듈 신설 (3 LLM 도구 + 1 헬퍼). `get_chat_rooms`/`get_chat_messages`/`send_chat_message` + `_resolve_chat_room_candidates`/`_do_send_chat_message` + `analyze_chat_consensus` + `CONSENSUS_SYSTEM_PROMPT` + `_CONSENSUS_FALLBACK` → `agent/tools/chat.py` (735 lines). 도구 3개에만 `@tool(groups=("chat",))` 등록, `analyze_chat_consensus` 는 `@tool` 없이 같은 모듈에 둠 (chat_ws.py 가 직접 import). orchestrator.py 의 `TOOLS_CHAT` 리터럴 (87 lines) 제거 → `from app.services.agent import TOOLS_CHAT` 로 교체.
  - 같이 처리 (PR 4 예정) — `get_incoming_subscription_requests` → `agent/tools/subscription.py` 로 이동.
  - PR 4 — `_shared.py` 통합. `_UUID_PATTERN`/`_run_async_in_thread`/`_service_error_payload`/`_sync_calendar_events_for_order_id`/`_find_seller_by_name`/`_find_product_by_name`/`_deduct_seller_stock_for_order` → `agent/_shared.py` 이동. agent_tools.py 의 helper 본문을 re-export shim 으로. 모든 도메인 모듈의 lazy import 도 `from .._shared import ...` 로 교체.
  - PR 5 — agent_tools.py 완전 제거. orchestrator import 를 `from app.services.agent import ...` 로 직접 교체.

#### 도구 모듈화 리팩터링 — PR 3: chat 도메인 모듈 신설 (2026-05-04 완료)
- PR 3 의 핵심 가치 — **TOOLS_CHAT 도 registry 통일 + LLM 외 함수 격리**: 옛 구조에서 `TOOLS_CHAT` 은 orchestrator.py 가 87줄 리터럴로 들고 있었고, `analyze_chat_consensus` 는 agent_tools.py 의 chat 도구 함수들과 섞여 있어 "이 함수는 LLM 도구인가 헬퍼인가?" 가 코드만 봐서는 헷갈렸음. PR 3 으로 (a) 3 도구는 `@tool` 데코레이터로 명시적 LLM 도구 선언, (b) `analyze_chat_consensus` 는 같은 모듈 하단에 `# === LLM 도구 외 함수 ===` 주석으로 격리 + ToolRegistry 미등록 → 의도가 코드에서 자명해짐.
- 신규 / 수정 파일:
  - `backend/app/services/agent/tools/chat.py` (735 lines, 신규) — 3 도구 + helper 2종 + analyze_chat_consensus + CONSENSUS_SYSTEM_PROMPT + _CONSENSUS_FALLBACK. agent_tools.py 의 chat 섹션 본문 그대로 복사 + `@tool` 데코레이터 추가 (3개만). `_resolve_chat_room_candidates`/`_do_send_chat_message` 는 도메인 internal helper 라 `@tool` 없이 그대로 둠.
  - `backend/app/services/agent/tools/__init__.py` (+1 line) — `from . import chat  # noqa: F401` 추가 → 8 도메인 모듈 모두 import.
  - `backend/app/services/agent_tools.py` (-671 lines, 1097→486 lines) — chat 3 도구 + analyze_chat_consensus 본문 제거 + re-export shim 으로 변환. `from app.services.agent.tools.chat import (...)` 4 항목 (도구 3 + analyze_chat_consensus). TOOL_FUNCTION_MAP 머지에서 chat 3 항목 제거 → 41 (40 registry + 1 잔존 subscription).
  - `backend/app/services/orchestrator.py` (-87 lines, 2244→2156 lines) — `TOOLS_CHAT = [...]` 리터럴 (87 lines, 3 schema) 제거 → `from app.services.agent import TOOLS_CHAT as _REGISTRY_TOOLS_CHAT; TOOLS_CHAT = _REGISTRY_TOOLS_CHAT` 2 lines 로 교체. `chat_node` 의 `tools=TOOLS_CHAT` 사용은 변경 없음 (변수명 보존).
  - `backend/tests/test_agent_registry.py` (+63 lines, 211→251 lines) — `_PR2_DOMAIN_MODULES` → `_PR3_DOMAIN_MODULES` rename + chat 추가, `test_domain_modules_register_37_tools` → `test_domain_modules_register_40_tools`, 신규 2 케이스: `test_chat_tools_in_chat_group_only`, `test_analyze_chat_consensus_not_registered`.
- 검증 (모두 PASSED):
  1. `pytest tests/test_agent_registry.py` — 12/12 통과 (10 기존 + 신규 2: chat 그룹 격리 + analyze_chat_consensus 미등록).
  2. agent registry: `TOOL_FUNCTION_MAP=40 / TOOLS=33 / TOOLS_CALENDAR=4 / TOOLS_CHAT=3` — 33 + 4 + 3 = 40 정확.
  3. agent_tools shim: `TOOL_FUNCTION_MAP=41 / TOOLS_CHAT=3 / analyze_chat_consensus callable` — 잔존 1 (subscription) 만 직접 등록.
  4. orchestrator: `TOOLS_CHAT=3` (registry import), `TOOLS=35` (33 + 2 잔존 inline schema, 변경 없음).
  5. chat_ws.py 직접 import 호환: `from app.services.agent_tools import analyze_chat_consensus, _find_product_by_name, _sync_calendar_events_for_order_id, find_alternative_partners, create_calendar_event, create_order` 모두 정상.
  6. 회귀 검사: `chat_node` 의 `tools=TOOLS_CHAT` 사용처 변경 없음, full unit test suite 동일한 4 pre-existing failure (PR 3 무관).
- **검증된 패턴 — `@tool` 없는 함수를 같은 모듈에 두는 격리 원칙**: `analyze_chat_consensus` 는 chat 도메인 의미적으로는 chat 모듈에 살아야 하지만, LLM 도구가 아니라 chat_ws.py 가 직접 호출하는 background 분석 함수. 별도 파일을 만들지 않고 같은 모듈 하단에 `# === LLM 도구 외 함수 ===` 주석 섹션으로 분리 + `@tool` 미부착. ToolRegistry 가 자동으로 LLM 노출에서 제외하므로 별도 코드 변경 없이 격리됨. CONSENSUS_SYSTEM_PROMPT / _CONSENSUS_FALLBACK 같은 동반 상수도 같은 섹션에 둠.
- **검증된 패턴 — chat 도메인 helper 가 같은 모듈에 함께 사는 자연스러움**: `_resolve_chat_room_candidates` / `_do_send_chat_message` 는 send_chat_message 만 사용하는 internal helper. order/subscription 같은 다른 도메인 모듈에서는 lazy import 안 함. 도메인 모듈은 자신의 internal helper 를 module-level 에 둘 수 있고, cross-domain helper (`_UUID_PATTERN`) 만 lazy import — 이 분리가 코드 가독성과 PR 4 의 _shared.py 마이그레이션 모두 단순하게 만든다.
- **검증된 함정 — 옛 test 가 silent pass 하는 사례**: PR 3 적용 전, `test_domain_modules_register_37_tools` 는 `_PR2_DOMAIN_MODULES` 에 chat 모듈을 포함하지 않아 chat 등록이 silent skip 되었지만 (registry clear 후 import 시 chat 은 안 등록됨), 테스트 자체는 37 을 expect 하므로 통과했다. PR 3 에서 `_PR3_DOMAIN_MODULES` 에 chat 추가 + expect 40 으로 동시 변경 안 하면 (a) 37 expect → 40 actual 로 실패, 또는 (b) chat 모듈을 _PR3 에 추가하지 않으면 silent skip 으로 잘못된 안전감 발생. **새 도메인 모듈 추가 시 test 의 _PR{n}_DOMAIN_MODULES 리스트도 동시에 업데이트하는 것이 PR-by-PR 회귀 차단의 핵심**.

#### 도구 모듈화 리팩터링 — PR 5: int_fields 자동 추출 + 도구 smoke 테스트 (2026-05-04 완료)
- PR 5 의 핵심 가치 — **도구 시그니처가 단일 진실의 원천 (Single Source of Truth)**: 옛 구조에서는 도구 함수의 `quantity: int` 어노테이션과 `@tool(int_fields=frozenset({"quantity"}))` 명시가 두 곳에 따로 적혀 있어 한쪽만 갱신해도 silent 누락이 가능했다 (`get_calendar_events.year/month`, `get_chat_messages.limit` 가 그 사례 — 시그니처는 int 인데 명시는 누락). PR 5 가 `tool(int_fields=None)` 을 기본값으로 두고 데코레이터 내부에서 `_auto_int_fields(fn)` 으로 함수 시그니처를 inspect 해 자동 추출하면서, 명시값이 있으면 명시 우선·없으면 자동 — **명시 + 자동 병행 fallback** 패턴 채택.
- 변경 파일 (1):
  - `backend/app/services/agent/_registry.py` (+60 lines, 105 → 165 lines) — `_auto_int_fields(fn)` 헬퍼 추가, `tool(...)` 의 `int_fields: frozenset[str] | None = None` 기본값으로 전환, 데코레이터 내부에서 `int_fields if int_fields is not None else _auto_int_fields(fn)` 로 분기. `types.UnionType` (PEP 604 `int | None`) 과 `typing.Union` (`Optional[int]` / `Union[int, None]`) 둘 다 처리.
- 신규 테스트 파일 (2):
  - `backend/tests/test_auto_int_fields.py` (17 케이스) — `_auto_int_fields` raw 함수 테스트 11종 (int, Optional[int], int|None, str 제외, default 값, 어노테이션 없음, list[int] 제외, return 무시, 평가 실패 시 빈 set) + 데코레이터 통합 4종 (auto 추출, 명시 우선, 빈 frozenset 명시 = 자동 끄기, int 없는 함수) + 도메인 모듈 적용 검증 2종 (기존 명시값 보존, year/month/limit 신규 자동 추출).
  - `backend/tests/test_tools_smoke.py` (18 케이스) — 8 도메인 모듈 로드 검증, 41 도구 등록 카운트, 그룹 분포 (34/4/3), schema 형식 검증 (name/description/parameters), 도구별 시그니처 sanity (get_products/create_order/find_alternative_partners/create_subscription_request/submit_counter_offer/get_user_profile/get_calendar_events/get_chat_rooms/get_chat_messages), `analyze_chat_consensus` 미등록 + callable, `_find_product_by_name` / `_shared` 헬퍼 import 검증.
- 검증 (모두 PASSED, 47/47):
  1. `pytest tests/test_agent_registry.py tests/test_auto_int_fields.py tests/test_tools_smoke.py --noconftest` — 12 + 17 + 18 = **47 passed**.
  2. `INT_FIELDS` 자동 합집합 = `{limit, min_order_qty, month, new_quantity, new_unit_price, price_per_unit, proposed_total_amount, quantity, stock_quantity, unit_price, year}` (11 필드). 기존 명시 8 필드 보존 + 자동 3 신규 (`year`, `month`, `limit`) — superset 안전.
  3. orchestrator.execute_tool 의 inline `INT_FIELDS = {...}` 8 필드 (옛 하드코딩) 와 비교: registry 자동 합집합이 추가로 `limit` 까지 잡아 더 정확. orchestrator 본체 통합은 별도 PR.
- **검증된 패턴 — `_auto_int_fields(fn)` PEP 604 호환 추출**:
  ```python
  def _auto_int_fields(fn):
      try: hints = get_type_hints(fn)
      except Exception: return frozenset()  # forward-ref 평가 실패 시 안전
      result = set()
      for param_name, hint in hints.items():
          if param_name == "return": continue
          if hint is int: result.add(param_name); continue
          origin = get_origin(hint)
          # typing.Union (Optional[int]) + types.UnionType (int | None) 둘 다 처리
          if origin is Union or origin is types.UnionType:
              args = [a for a in get_args(hint) if a is not type(None)]
              if len(args) == 1 and args[0] is int:
                  result.add(param_name)
      return frozenset(result)
  ```
  - `from __future__ import annotations` 가 도메인 모듈에 적용되어 어노테이션이 문자열로 보존돼도 `typing.get_type_hints(fn)` 이 평가해 실제 타입 객체로 변환. raw `__annotations__` 비교는 작동 안 함 (테스트도 `get_type_hints` 사용 필수).
  - `list[int]` / `Optional[list[int]]` 같은 컨테이너 타입은 LLM 입력에서 직접 변환 대상이 아니므로 제외 (origin 이 list 라 Union 분기로 안 들어감).
- **검증된 패턴 — `int_fields=None` vs `int_fields=frozenset()` 의미 구분**: 두 값을 모두 허용하되 서로 다른 의미.
  - `None` (기본): "선언 안 함 → 자동 추출 적용"
  - `frozenset()` (빈 frozenset 명시): "이 도구는 int 변환 대상 0개 — 자동 추출도 끄기" (강제 선언)
  - 이 분리가 없으면 default 값이 `frozenset()` 일 경우 자동 추출이 영영 안 켜진다. `None` 을 sentinel 로 사용하는 패턴이 표준.
- **검증된 함정 — `from __future__ import annotations` 적용 모듈에서 raw `__annotations__` 비교 무용**: `inspect.get_annotations(fn)` 또는 `fn.__annotations__` 는 stringified 된 어노테이션 (`'int'`) 을 그대로 반환해 `is int` 비교가 항상 False. 반드시 `typing.get_type_hints(fn)` 으로 실제 타입 객체로 평가한 뒤 비교. 도메인 도구가 모두 `from __future__ import annotations` 사용하므로 `_auto_int_fields` 와 테스트 둘 다 `get_type_hints` 사용 필수. raw annotation 으로 짠 첫 시도 테스트 2개가 `'int' is int` 로 실패한 사례 — 항상 `get_type_hints` 우선.
- **smoke 테스트 설계 원칙**: 도구당 깊은 비즈니스 로직 (모든 분기, RLS, race condition) 까지 mock 으로 검증하는 건 비용 대비 회귀 가치가 낮다. PR 5 는 "import → 등록 → callable → schema 형식 → 시그니처 키워드 sanity" 의 5단계 smoke 만 커버. 깊은 mock 테스트는 도구별 버그가 실제 발생할 때 핀포인트로 추가 (회귀 진단 비용이 발생할 때만). 이 원칙으로 PR 5 의 18 smoke 테스트가 **0.04 초** 안에 8 도메인 + 41 도구 등록 정합성 검증을 한 사이클에 끝냄.

#### response_node fab 검사 intent 게이트 — CALENDAR/CHAT/GENERAL 응답 보호 (2026-05-04 회귀 수정)
- **회귀 증상**: 사용자 "캘린더 5월 일정 보여줘" → AI "주문 처리 중 문제가 발생했습니다. 다시 말씀해 주시면 처리해 드리겠습니다." 라우팅·도구 호출은 모두 정상이었으나 response_node 의 fab(날조) 안전망이 calendar 응답을 잘못 차단.
- **원인**: response_node 의 `_order_fab_markers = ["ORD-", "주문 번호는", "주문번호는", "접수되었습니다", "견적 요청으로 전달"]` 검사가 intent 와 무관하게 모든 응답에 적용됐다. `agent.tools.calendar.get_calendar_events` 가 `calendar_events.orders!order_id(order_number, ...)` 임베딩을 flatten 해서 `order_number` 를 응답에 포함시키면, calendar_data_node 의 LLM 이 "5월 15일 옥수수 80kg 배송 (주문번호: ORD-20260515-0001)" 처럼 자연어 풀이를 한다. 이 응답이 fab 마커 `'ORD-'` 를 트리거 → fab fallback 메시지로 교체되어 사용자가 보는 결과는 "주문 처리 중 문제".
- **수정**: `if intent in ("INVENTORY", "ORDER"):` 게이트로 fab 검사 3종(`_order_fab_markers` / `_delivery_fab_markers` / `_counter_offer_fab_markers`) 전체를 감쌌다. CALENDAR / CHAT / GENERAL intent 의 응답은 fab 검사를 거치지 않는다 — 해당 노드들은 자체적으로 도구 호출/검증을 완료하므로 응답에 ORD- 토큰이 있어도 정상 데이터.
- **단위 테스트**: `backend/tests/test_orchestrator_response_fab_gate.py` (7 케이스) 추가 — CALENDAR + ORD-, CHAT + ORD-, ORDER fab 차단 정상, ORDER + create_order 정상, ORDER + get_orders 정상, INVENTORY + 납품일 fab 차단, CALENDAR + 납품일 마커 통과. 모두 PASSED.
- **핵심 교훈 — fab 안전망은 intent gate 가 필수**: 응답 콘텐츠 기반 마커 검사는 false positive 가 항상 발생한다 (특히 도구가 임베딩으로 cross-domain 데이터를 가져올 때). intent 별로 어떤 노드가 final_response 를 채웠는지 명시적으로 게이트해야 한다. CALENDAR 노드가 채운 응답에 "ORD-" 가 있으면 정상, INVENTORY/ORDER 노드가 채운 응답에 "ORD-" 가 있는데 create_order 호출 흔적이 없으면 환각. 둘은 정반대 케이스라 같은 마커로 묶어서 검사하면 안 됨.
- **재발 방지**: 새 fab 마커 추가 시 intent gate 안쪽에 추가하고, 다른 intent 응답에서 우연히 해당 키워드를 정상적으로 사용할 수 있는지 검토 필수. `response_node` 의 모든 short-circuit return 은 어느 intent 의 결과를 차단하는지 주석으로 명시.
