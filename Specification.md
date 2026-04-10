# 개발 명세서 (Claude Code 실행용)

> 이 문서는 팀원 Claude Code가 AgriFlow를 완성할 수 있도록 현재 상태, 버그, 미구현 기능, 구현 지시를 상세히 기술한다.
> 모든 작업은 CLAUDE.md의 서브에이전트 위임 원칙을 따른다.
> **최종 업데이트**: 2026-04-10 v5 — validator_node 구현 완료(4노드 전환), partners.deleted_at 컬럼 Supabase 대시보드로 추가 완료, 프롬프트 판매의도/재고등록 구분 원칙 추가, migration 타임스탬프 충돌 주의사항 추가

---

## 1. 현재 구현 상태 요약 (실제 코드 기준)

### ✅ 구현 완료

| 영역 | 내용 |
|------|------|
| Backend API | 33개 엔드포인트 (섹션 3 상세 목록) — 중복 없음 확인 |
| DB 테이블 | users, products, partners, orders, order_items, chat_rooms, messages, calendar_events, ai_conversations |
| AI 오케스트레이터 | LangGraph **TEA 방식 4노드** (orchestrator_node[Analyzer] → inventory_order_node[Executor] → validator_node[Validator] → response_node) + OpenAI gpt-4o-mini |
| AI 도구 함수 | agent_tools.py — 13개 함수 / TOOL_FUNCTION_MAP 13개 / orchestrator TOOLS 13개 **모두 일치** |
| 캘린더 에이전트 | schedule_agent.py — SELLER/BUYER 프롬프트 분리 완료 (`_build_system_prompt` L111) / JSON 강제 완료 (L242) |
| WebSocket 채팅 | chat_ws.py — JWT 인증 + 브로드캐스트 완료 |
| WebSocket 훅 | useWebSocketChat.ts — 자동 재연결(최대 3회) |
| AI 일정 추천 패널 | ScheduleAgentPanel.tsx — 캘린더 페이지 통합 |
| 인증 | Supabase Auth + JWT |
| RLS | 전체 테이블 적용 |
| 멤버 관리 | users.py API + user_service.py — main 브랜치 병합 완료 |
| 판매자 대시보드 | 출하·견적·재고부족 카드 실데이터 연동 완료 |
| 구매자 대시보드 | 진행중 주문·견적·배송 카드 실데이터 연동 완료 |
| 구매자 browse | 카테고리 필터 + 상품 카드 렌더링 완료 |
| validator_node | LangGraph 4노드 전환 완료 — PASSED/RETRY/FAILED 판정, MANUAL_REVIEW 태그 |
| partners.deleted_at | Supabase 대시보드에서 컬럼 직접 추가 완료 |

### ❌ 미구현 / 미완성 (파일:라인 근거 포함)

| 기능 | 실제 상태 | 수정 파일 | 할 것 |
|------|----------|----------|-------|
| ~~BUG-1 `.is_("deleted_at","null")`~~ | ~~product_service(L35,L64), order_service(L47,L84), calendar_service(L31), schedule_agent(L47·L59·L80·**L96**), **user_service(L45,L85)**, **partner_service(L41)**, **ai_context(L38)**~~ | ~~위 7개 파일 총 13곳~~ | ✅ 수정 완료 |
| ~~BUG-2 `.single()` order_service~~ | ~~`order_service.py` 에 존재~~ | ~~order_service.py~~ | ✅ 수정 완료 |
| ~~BUG-3 `.single()` product_service~~ | ~~`product_service.py` 에 존재~~ | ~~product_service.py~~ | ✅ 수정 완료 |
| ~~BUG-4 `.single()` user_service~~ | ~~`user_service.py:86` 에 존재~~ | ~~user_service.py~~ | ✅ 수정 완료 |
| `POST /ai/chat` 중복 | `ai_assistant.py:55` 미사용 엔드포인트 존재 | ai_assistant.py | 라우터 제거 |
| `get_calendar_events` tool | agent_tools.py 에 없음 | agent_tools.py, orchestrator.py | 구현 + TOOLS/MAP 등록 |
| `create_calendar_event` tool | agent_tools.py 에 없음 | agent_tools.py, orchestrator.py | 구현 + TOOLS/MAP 등록 |
| `find_alternative_partners` tool | agent_tools.py 에 없음 | agent_tools.py, orchestrator.py | 구현 + TOOLS/MAP 등록 |
| `get_user_profile` tool | agent_tools.py 에 없음 | agent_tools.py, orchestrator.py | 구현 + TOOLS/MAP 등록 (user_service.py 활용) |
| `analyze_chat_consensus` tool | agent_tools.py 에 없음 | agent_tools.py | 구현 (orchestrator TOOLS 미등록 — chat_ws.py 직접 호출) |
| ~~`validator_node`~~ | ~~orchestrator.py 에 없음~~ | ~~orchestrator.py~~ | ✅ 구현 완료 (orchestrator.py) |
| `response_node` 단락회로 | `orchestrator.py:772` message 있으면 LLM 미통과 | orchestrator.py | 재고 부족 시 LLM 통과 조건 수정 |
| orchestrator 프롬프트 고도화 | 기본 수준 | orchestrator.py | AGENT_SELLER/BUYER_SYSTEM + few-shot 추가 (섹션 9.1) |
| `send_private_message` | connection_manager.py 에 없음 | connection_manager.py | user_id 기반 개별 전송 구현 |
| chat_ws.py 합의 감지 분기 | chat_ws.py 에 없음 | chat_ws.py | 4가지 case + 쿨다운 로직 (섹션 8.2) |
| AI 히스토리 프론트 연동 | ai-assistant/page.tsx:11 useAIStream만 있음 | useAIHistory.ts (신규), ai-assistant/page.tsx x2 | 훅 생성 + 페이지 연결 (섹션 5.1) |
| 대시보드 미확인 채팅 카운트 | seller/dashboard:57, buyer/dashboard:62 하드코딩 0 | dashboard/page.tsx x2 | GET /chat/rooms unread_count 연동 |
| browse 견적 요청 버튼 | buyer/browse/page.tsx:101 disabled만 처리 | buyer/browse/page.tsx | 클릭 → 채팅방 생성 → AI 견적 메시지 자동 발송 |
| `GET /products` 필터 추가 | max_price, min_stock 파라미터 없음 | products.py, product_service.py | 쿼리 파라미터 추가 |
| MANUAL_REVIEW 배너 | 프론트 코드 없음 | ai-assistant/page.tsx x2 | 노란색 경고 배너 조건부 렌더링 |
| ~~`partners.deleted_at 컬럼 없음`~~ | ~~partners 테이블에 deleted_at 컬럼 없음 — partner_service.py에서 임시로 hard delete로 변경~~ | ~~Supabase 대시보드에서 `20260410000001_add_partners_deleted_at.sql` 실행 필요~~ | ✅ Supabase 대시보드에서 직접 추가 완료 |
| ~~`판매자 "팔고싶어" 의도 처리`~~ | ~~AGENT_SELLER_SYSTEM에 [판매 의도 처리 원칙] 추가 완료 — find_buyers_by_product 연결~~ | ~~orchestrator.py~~ | ✅ 완료 |
| ~~`"재고 등록" → create_product 구분`~~ | ~~AGENT_SELLER_SYSTEM에 [의도 구분 원칙] 추가 완료~~ | ~~orchestrator.py~~ | ✅ 완료 |
| DB 마이그레이션 | 20260408000001_update_unit_constraint.sql 미실행 | Supabase 대시보드 | SQL Editor에서 직접 실행 |

---

## 2. 데이터 조회 오류 근본 원인 (최우선 해결)

> ⚠️ AI가 "등록된 상품이 없습니다", "주문 내역이 없습니다"라고 대답하는 심각한 버그.

### BUG-1: `.is_("deleted_at", "null")` 문자열 버그

> ✅ **수정 완료** (2026-04-10)

**원인**: Supabase Python 클라이언트 `.is_()` 에 `"null"` 문자열을 넘기면 SQL `IS 'null'`(문자열 비교)로 쿼리된다. `deleted_at` 컬럼은 SQL `NULL`이므로 **모든 행이 필터링**되어 빈 결과 반환.

```python
# 잘못된 코드
query.is_("deleted_at", "null")

# 올바른 코드
query.is_("deleted_at", None)
```

**수정 위치 (실제 코드 전수조사 — 총 9곳)**:
- `product_service.py` — L35, L64 (2곳)
- `order_service.py` — L47, L84 (2곳)
- `calendar_service.py` — L31 (1곳)
- `schedule_agent.py` — L47, L59, L80, **L96** (4곳 — L96 주의)
- `user_service.py` — L45, L85 (2곳)
- `partner_service.py` — L41 (1곳)
- `ai_context.py` — L38 (1곳)

> ⚠️ **agent_tools.py는 이미 `None` 사용 중** — 수정 불필요.

### BUG-2: `order_service.get_order()` `.single()` PGRST116

> ✅ **수정 완료** (2026-04-10)

**원인**: `.single()`은 결과 0건일 때 PGRST116 예외 발생.

```python
# 수정 전
.is_("deleted_at", "null").single().execute()

# 수정 후
.is_("deleted_at", None).execute()
# 반환: result.data[0] if result.data else None
```

### BUG-3: `product_service.get_product()` — BUG-2와 동일 패턴

> ✅ **수정 완료** (2026-04-10)

`product_service.py` 동일하게 수정.

### BUG-4: `user_service.py:86` `.single()` — BUG-2와 동일 패턴

> ✅ **수정 완료** (2026-04-10)

`user_service.py:86` — `.single()` 제거, `result.data[0] if result.data else None` 패턴으로 교체.

---

## 3. 백엔드 API 전체 목록 (실제 코드 기준)

| 파일 | 메서드 | 경로 | 상태 |
|------|--------|------|------|
| users.py | GET | `/api/v1/users/me` | 정상 |
| users.py | PATCH | `/api/v1/users/me` | 정상 |
| users.py | GET | `/api/v1/users/search` | 정상 |
| users.py | GET | `/api/v1/users/{user_id}/profile` | 정상 |
| products.py | GET | `/api/v1/products` | `max_price`, `min_stock` 파라미터 추가 필요 |
| products.py | GET | `/api/v1/products/{product_id}` | 정상 |
| products.py | POST | `/api/v1/products` | 정상 |
| products.py | PATCH | `/api/v1/products/{product_id}` | 정상 |
| products.py | DELETE | `/api/v1/products/{product_id}` | 정상 |
| orders.py | GET | `/api/v1/orders` | 정상 |
| orders.py | GET | `/api/v1/orders/{order_id}` | 정상 |
| orders.py | POST | `/api/v1/orders` | 정상 |
| orders.py | PATCH | `/api/v1/orders/{order_id}/status` | 정상 |
| partners.py | GET | `/api/v1/partners` | 정상 |
| partners.py | POST | `/api/v1/partners` | 정상 |
| partners.py | PATCH | `/api/v1/partners/{partner_id}` | 정상 |
| partners.py | DELETE | `/api/v1/partners/{partner_id}` | 정상 |
| chat.py | GET | `/api/v1/chat/rooms` | 정상 |
| chat.py | POST | `/api/v1/chat/rooms` | 정상 |
| chat.py | GET | `/api/v1/chat/rooms/{room_id}/messages` | 정상 |
| chat.py | POST | `/api/v1/chat/rooms/{room_id}/messages` | 정상 |
| chat.py | POST | `/api/v1/chat/rooms/{room_id}/read` | 정상 |
| calendar.py | GET | `/api/v1/calendar` | 정상 |
| calendar.py | POST | `/api/v1/calendar` | 정상 |
| calendar.py | PATCH | `/api/v1/calendar/{event_id}` | 정상 |
| calendar.py | DELETE | `/api/v1/calendar/{event_id}` | 정상 |
| ai_assistant.py | POST | `/api/v1/ai/chat` | **⛔ 제거 대상 — 미사용 중복 (L55)** |
| ai_assistant.py | POST | `/api/v1/ai/summarize-chat` | 정상 (Claude) |
| ai_assistant.py | POST | `/api/v1/ai/daily-summary` | 정상 (Claude) |
| ai_assistant.py | POST | `/api/v1/ai/agent/chat` | **메인 AI 오케스트레이터** (프론트 연결됨) |
| ai_assistant.py | GET | `/api/v1/ai/history` | 정상 |
| schedule_agent.py | POST | `/api/v1/schedule-agent/recommend` | 정상 |
| chat_ws.py | WebSocket | `/ws/chat/{room_id}` | 정상 |

**총 33개. `/api/v1/ai/chat` 제거 후 32개.**

---

## 4. AI 에이전트 명세서

### 4.1 현재 LangGraph 구조 (4노드 — TEA 방식)

```
사용자 입력
    ↓
orchestrator_node (Analyzer) — intent만 분류, tool 없음 (OpenAI gpt-4o-mini, response_format=json_object)
    ↓ INVENTORY/ORDER → inventory_order_node
    ↓ GENERAL → final_response 직접 설정
inventory_order_node (Executor) — 자체 LLM + TOOLS, 최대 3회 tool 루프
    ↓
validator_node (Validator) — tool 결과 검증, PASSED/RETRY/FAILED 판정
    ↓ PASSED → response_node
    ↓ RETRY (tool_round < 2) → inventory_order_node 재시도
    ↓ FAILED (tool_round >= 2) → response_node (manual_review=True)
response_node — 최종 답변 생성 (AGENT_SELLER/BUYER_SYSTEM 사용)
```

### 4.2 ~~목표~~ 구현 완료 LangGraph 구조

> ✅ **구현 완료** (2026-04-10)

```
orchestrator_node (Analyzer)
    ↓
inventory_order_node (Executor) ←──────────────┐
    ↓                                           │ RETRY (tool_round < 2)
validator_node (결과 검증 — 신규)               │
    ↓ PASSED ──→ response_node → END            │
    ↓ RETRY ────────────────────────────────────┘
    ↓ FAILED (tool_round >= 2) ──→ response_node (MANUAL_REVIEW 태그) → END
```

**validator_node 판단 기준**:
- tool_results 중 `success: false` 존재 → RETRY 또는 FAILED
- tool_results 모두 성공 또는 tool 미사용 → PASSED
- RETRY는 orchestrator_node가 아닌 inventory_order_node로 돌아감 (intent 재분류 불필요)

### 4.3 구현된 Tool 목록 (agent_tools.py — 13개, 전수조사 완료)

| Tool 함수 | 설명 | 입력 | 출력 |
|-----------|------|------|------|
| `get_products` | 판매자 상품 목록 조회 | seller_id, category? | products[], count |
| `check_stock` | 상품 재고 상세 조회 | product_id?, seller_id?, product_name? | product{} |
| `update_stock` | 재고 수량 변경 | product_id?, new_quantity, seller_id?, product_name? | success, new_quantity, new_status |
| `create_product` | 상품 등록 | seller_id, name, category, price_per_unit, stock_quantity, unit | success, product_id |
| `update_product` | 상품 정보 수정 | seller_id, product_id?, product_name?, 변경필드 | success |
| `delete_product` | 상품 삭제 (soft) | product_id?, seller_id, name? | success |
| `get_orders` | 주문 목록 조회 | user_id, role, status? | orders[], count |
| `get_order_detail` | 주문 상세 조회 | order_id | order{} |
| `update_order_status` | 주문 상태 변경 | order_id, new_status | success |
| `create_order` | 주문 생성 | buyer_id, seller_id, items[], delivery_date? | success, order_id |
| `delete_order` | 주문 삭제 | order_id, user_id | success |
| `find_sellers_by_product` | 카테고리로 판매자 탐색 | category, product_name? | sellers[] |
| `find_buyers_by_product` | 카테고리로 구매자 탐색 | category | buyers[] |

> **⚠️ 최신 user_service.py 활용 주의**: main 브랜치 병합된 `search_users(query, role)` / `get_user_profile(user_id)` 를 직접 호출. Supabase 쿼리를 agent_tools.py에서 중복 구현하지 말 것.

### 4.4 추가 구현 필요한 Tool (agent_tools.py에 신규 추가)

#### `get_calendar_events`
```python
def get_calendar_events(user_id: str, year: int, month: int) -> dict:
    """사용자의 특정 월 일정을 조회한다."""
    # calendar_events 테이블에서 user_id + 날짜 범위 필터
    # 반환: {"success": True, "events": [...], "count": N}
```

#### `create_calendar_event`
```python
def create_calendar_event(
    user_id: str,
    title: str,
    event_date: str,       # YYYY-MM-DD
    event_type: str,       # SHIPMENT | DELIVERY | MEETING | QUOTE_DEADLINE | ORDER
    description: str = "",
    order_id: str = "",
) -> dict:
    # 반환: {"success": True, "event_id": "...", "title": "..."}
```

#### `find_alternative_partners`
```python
def find_alternative_partners(
    user_id: str,
    role: str,             # SELLER | BUYER
    category: str,
    reason: str = "",
) -> dict:
    """
    대체 거래처 탐색.
    - BUYER 호출: 해당 카테고리 상품 보유 판매자 반환
    - SELLER 호출: 해당 카테고리 주문 이력 있는 구매자 반환
    DB 결과를 LLM에 넘겨 상황에 맞는 추천 순위 결정 (단순 정렬 금지)
    반환: {"success": True, "alternatives": [{user_id, name, company, trade_count, ...}]}
    """
```

#### `get_user_profile`
```python
def get_user_profile(user_id: str = "", username: str = "", company_name: str = "") -> dict:
    """
    유저 프로필 조회. user_id 또는 username/company_name 중 하나 이상 필요.
    user_service.py의 search_users / get_user_by_id 활용.
    반환: {"success": True, "user": {id, username, role, company_name, phone, ...}}
    """
```

**orchestrator TOOLS 등록** (find_alternative_partners와 같은 방식):
```python
{
    "type": "function",
    "function": {
        "name": "get_user_profile",
        "description": "거래 상대방 또는 자신의 유저 프로필 조회. user_id, 이름, 회사명으로 검색 가능.",
        "parameters": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "username": {"type": "string"},
                "company_name": {"type": "string"},
            },
            "required": [],
        },
    },
},
```

**TOOL_FUNCTION_MAP 추가**:
```python
"get_user_profile": get_user_profile,
```

**구현 참고**: `user_service.py`의 `search_users(query, role)` 와 `get_user_profile(user_id)` 활용. main 브랜치 병합 완료된 최신 코드 그대로 호출.

---

#### `analyze_chat_consensus` (chat_ws.py 전용 — orchestrator TOOLS 미등록)
```python
def analyze_chat_consensus(room_id: str, last_n_messages: int = 10) -> dict:
    """
    채팅방 최근 메시지 분석 → 합의 여부 판단.
    내부에서 OpenAI 동기 클라이언트 사용 (asyncio.run 사용 금지 — 이벤트루프 충돌).
    chat_ws.py에서 asyncio.to_thread()로 호출할 것.
    반환:
    {
        "status": "consensus" | "negotiating" | "rejected" | "general",
        "confidence": float | None,
        "extracted": {
            "product": str, "quantity": int, "unit": str,
            "price_per_unit": int, "delivery_date": str,
            "buyer_id": str, "seller_id": str
        }
    }
    """
```

### 4.5 orchestrator.py TOOLS 추가 정의 (3개 추가)

```python
# orchestrator.py TOOLS 리스트에 추가
{
    "type": "function",
    "function": {
        "name": "get_calendar_events",
        "description": "사용자의 특정 월 일정을 조회한다. 사용자가 일정을 물어보거나 캘린더를 확인하고 싶을 때 사용.",
        "parameters": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "year": {"type": "integer"},
                "month": {"type": "integer"},
            },
            "required": ["user_id", "year", "month"],
        },
    },
},
{
    "type": "function",
    "function": {
        "name": "create_calendar_event",
        "description": "일정을 등록한다. 자연어로 일정 등록 요청 시 날짜/제목/유형 해석 후 등록. create_order 성공 시 자동 연쇄 호출할 것.",
        "parameters": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "title": {"type": "string"},
                "event_date": {"type": "string", "description": "YYYY-MM-DD"},
                "event_type": {"type": "string", "description": "SHIPMENT | DELIVERY | MEETING | QUOTE_DEADLINE | ORDER"},
                "description": {"type": "string"},
                "order_id": {"type": "string"},
            },
            "required": ["user_id", "title", "event_date", "event_type"],
        },
    },
},
{
    "type": "function",
    "function": {
        "name": "find_alternative_partners",
        "description": "대체 거래처를 탐색한다. 재고 없거나 협상 결렬 시, 또는 사용자 직접 요청 시 사용.",
        "parameters": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "role": {"type": "string", "description": "SELLER 또는 BUYER"},
                "category": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["user_id", "role", "category"],
        },
    },
},
```

### 4.6 TOOL_FUNCTION_MAP 업데이트

```python
# agent_tools.py 하단 TOOL_FUNCTION_MAP에 추가
TOOL_FUNCTION_MAP = {
    # 기존 13개 유지 ...
    "get_calendar_events": get_calendar_events,
    "create_calendar_event": create_calendar_event,
    "find_alternative_partners": find_alternative_partners,
    "get_user_profile": get_user_profile,
    # analyze_chat_consensus 미등록 — chat_ws.py가 직접 호출
}
```

### 4.7 JSON 출력 강제 (파싱 에러 방지)

```python
response_format={"type": "json_object"}  # OpenAI API 호출 시 반드시 포함
```

**적용 대상 및 현황**:
| 파일 | 적용 여부 |
|------|----------|
| `schedule_agent.py` | ✅ 이미 적용 (L242) |
| `analyze_chat_consensus` (신규) | 구현 시 반드시 적용 |
| `validator_node` (신규) | 구현 시 반드시 적용 |

---

## 5. 프론트엔드 구현 지시

### 5.1 AI 채팅 기록 페이지 연동

**현재**: `ai_conversations` DB 저장 완료, 프론트 조회 미연동.
**API**: `GET /api/v1/ai/history?limit=50` (구현됨)

**`useAIHistory.ts` 훅 신규 생성**:
```typescript
// frontend/hooks/useAIHistory.ts
export function useAIHistory() {
  return useQuery({
    queryKey: ['ai-history'],
    queryFn: () => apiClient.get('/ai/history?limit=50'),
  });
}
```

**표시 방식**: 카카오톡 스타일 — 날짜 구분선 + 스크롤하면 이전 대화 위에 이어서 표시.
```
──── 2026-04-09 ────
사용자: 사과 재고 알려줘
AI: 현재 사과 후지 재고는 150박스입니다.
──── 2026-04-10 ────
사용자: 배추 주문 넣어줘
AI: 주문이 생성됐습니다.
[입력창]
```

**수정 파일**: `useAIHistory.ts` (신규), `seller/ai-assistant/page.tsx`, `buyer/ai-assistant/page.tsx`

### 5.2 대시보드 미확인 채팅 카운트 연동

**현재 상태**:
- `seller/dashboard/page.tsx:57` — 하드코딩 `0`
- `buyer/dashboard/page.tsx:62` — 하드코딩 `0`

**수정**: `GET /api/v1/chat/rooms` 응답의 `unread_count` 합산 후 카드에 표시.

### 5.3 사이드바 비율 통일

- 사이드바: `w-60` (240px)
- 메인 컨텐츠: `flex-1 min-w-0`
- 데스크탑 전용 (모바일 불필요)

### 5.4 구매자 상품 탐색 페이지 (`/buyer/browse`)

**현재 상태**: 카테고리 필터 + 상품 카드 완성. `buyer/browse/page.tsx:101` "견적 요청" 버튼 `disabled` 처리만 됨.

**추가 구현**:

1. **백엔드** `GET /products`에 `max_price`, `min_stock` 파라미터 추가
2. **프론트 필터 바** — 최대 단가, 최소 재고 입력 추가
3. **"견적 요청" 버튼 클릭 플로우** (AgenticPay 논문 기반):
   - `POST /chat/rooms` → 채팅방 생성
   - 채팅 페이지로 이동
   - AI가 채팅창에 견적 요청 텍스트 시스템 메시지 자동 발송:
     `"[견적 요청] 상품: {상품명} / 단가: {price}원 / 수량·납품일: 협의"`
   - 이후 자연어 멀티턴 협상 → `analyze_chat_consensus` 모니터링

### 5.5 MANUAL_REVIEW 배너

validator_node에서 `"tag": "MANUAL_REVIEW"` 또는 `"tag": "DATA_ANOMALY"` 반환 시:

```tsx
{hasManualReviewTag && (
  <div className="bg-yellow-50 border border-yellow-400 rounded p-3 mb-2 flex items-center gap-2">
    <span>⚠️</span>
    <span className="text-yellow-800 text-sm">
      AI 답변 검토 필요 — 처리 중 이상이 감지됐습니다. 결과를 직접 확인해 주세요.
    </span>
  </div>
)}
```

---

## 6. 구현 우선순위

### Phase 1 — 즉시 (버그 수정)

| # | 작업 | 파일:라인 |
|---|------|----------|
| 1 | BUG-1 `.is_("deleted_at","null")` → `None` 일괄 수정 | product_service.py(L35,L64), order_service.py(L47,L84), calendar_service.py(L31), schedule_agent.py(L47·L59·L80·L96), user_service.py(L45,L85), partner_service.py(L41), ai_context.py(L38) |
| 2 | BUG-2 `order_service.get_order()` `.single()` 제거 | order_service.py |
| 3 | BUG-3 `product_service.get_product()` `.single()` 제거 | product_service.py |
| 3-1 | BUG-4 `user_service.py:86` `.single()` 제거 | user_service.py |
| 4 | `POST /ai/chat` 제거 | ai_assistant.py:55 |

### Phase 2 — 핵심 AI 기능

| # | 작업 | 파일 |
|---|------|------|
| 5 | `get_calendar_events` 구현 + TOOLS/MAP 등록 | agent_tools.py, orchestrator.py |
| 6 | `create_calendar_event` 구현 + TOOLS/MAP 등록 | agent_tools.py, orchestrator.py |
| 7 | `find_alternative_partners` 구현 + TOOLS/MAP 등록 | agent_tools.py, orchestrator.py |
| 7-1 | `get_user_profile` 구현 + TOOLS/MAP 등록 (user_service.py 활용) | agent_tools.py, orchestrator.py |
| 8 | orchestrator.py AGENT_SELLER/BUYER_SYSTEM 프롬프트 고도화 + few-shot | orchestrator.py |
| 9 | `response_node:772` 단락회로 수정 (재고 부족 시 LLM 통과) | orchestrator.py |

### Phase 3 — 논문 기능 (AgenticPay + AgentOrchestra)

| # | 작업 | 파일 |
|---|------|------|
| 10 | `analyze_chat_consensus` 구현 (OpenAI 동기 클라이언트) | agent_tools.py |
| 11 | `connection_manager.py` `send_private_message(user_id)` 추가 | connection_manager.py |
| 12 | `chat_ws.py` 합의 감지 4가지 분기 + 쿨다운 로직 | chat_ws.py |
| 13 | `validator_node` 추가 + LangGraph 4노드 전환 | orchestrator.py |

### Phase 4 — 프론트엔드 완성

| # | 작업 | 파일:라인 |
|---|------|----------|
| 14 | `useAIHistory.ts` 훅 생성 + ai-assistant 페이지 연결 | useAIHistory.ts (신규), ai-assistant/page.tsx x2 |
| 15 | 대시보드 미확인 채팅 카운트 연동 | seller/dashboard:57, buyer/dashboard:62 |
| 16 | browse 견적 요청 버튼 플로우 구현 | buyer/browse/page.tsx:101 |
| 17 | `GET /products` max_price·min_stock 필터 | products.py, product_service.py |
| 18 | MANUAL_REVIEW 배너 | ai-assistant/page.tsx x2 |

---

## 7. 파일 경로 참조 (수정 필요 파일)

```
backend/
├── app/
│   ├── api/v1/
│   │   ├── ai_assistant.py    ← POST /ai/chat 제거 (Phase 1-4)
│   │   └── products.py        ← max_price, min_stock 파라미터 추가 (Phase 4-17)
│   ├── services/
│   │   ├── product_service.py ← BUG-1(L35,L64), BUG-3 수정 (Phase 1)
│   │   ├── order_service.py   ← BUG-1(L47,L84), BUG-2 수정 (Phase 1)
│   │   ├── calendar_service.py← BUG-1(L31) 수정 (Phase 1)
│   │   ├── schedule_agent.py  ← BUG-1(L47·L59·L80·L96) 수정 (Phase 1)
│   │   ├── user_service.py    ← BUG-1(L45,L85), BUG-4(L86) 수정 (Phase 1)
│   │   ├── partner_service.py ← BUG-1(L41) 수정 (Phase 1)
│   │   ├── ai_context.py      ← BUG-1(L38) 수정 (Phase 1)
│   │   ├── agent_tools.py     ← Tool 4개 신규 추가 (Phase 2·3)
│   │   └── orchestrator.py    ← TOOLS 3개 추가, 프롬프트 고도화,
│   │                             validator_node 추가, 단락회로 수정 (Phase 2·3)
│   └── websocket/
│       ├── chat_ws.py         ← 합의 감지 4가지 분기 + 쿨다운 (Phase 3-12)
│       └── connection_manager.py ← send_private_message 추가 (Phase 3-11)

frontend/
├── app/(dashboard)/
│   ├── seller/
│   │   ├── dashboard/page.tsx:57   ← 미확인 채팅 카운트 (Phase 4-15)
│   │   └── ai-assistant/page.tsx   ← 히스토리 연동 + MANUAL_REVIEW 배너 (Phase 4)
│   └── buyer/
│       ├── dashboard/page.tsx:62   ← 미확인 채팅 카운트 (Phase 4-15)
│       ├── browse/page.tsx:101     ← 견적 요청 버튼 플로우 (Phase 4-16)
│       └── ai-assistant/page.tsx   ← 히스토리 연동 + MANUAL_REVIEW 배너 (Phase 4)
└── hooks/
    └── useAIHistory.ts             ← 신규 생성 (Phase 4-14)

supabase/
└── migrations/
    └── 20260408000001_update_unit_constraint.sql ← Supabase 대시보드에서 직접 실행
```

---

## 8. 논문 기반 아키텍처 구현

### 8.1 AgentOrchestra — Validator 노드 분리

**핵심**: TEA Protocol — Analyzer(orchestrator) + Executor(inventory_order) + Validator(신규) 분리

**구현 지시**:
- ✅ **구현 완료** — orchestrator.py에 validator_node 추가, _build_graph() 4노드로 전환
- AgentState에 `validation_status: str`, `manual_review: bool` 필드 추가됨
- RETRY는 inventory_order_node로 돌아감 (orchestrator_node 재분류 불필요)
- `validator_node` 처리 로직:
  - `success=True` → PASSED → response_node
  - `success=False` + `tool_round < 2` → RETRY → inventory_order_node 재시도
  - `success=False` + `tool_round >= 2` → FAILED, tag=`MANUAL_REVIEW`
  - 논리적 이상(음수 재고 등) → tag=`DATA_ANOMALY`

**⚠️ ai_conversations 저장 로직 유지 필수**: 4노드 전환 후에도 `response_node` 또는 `ai_assistant.py` 라우터 단에서 반드시 저장 실행. 누락 시 히스토리 전체 깨짐.

**⚠️ MAX_TOOL_ROUNDS 정렬 필수**: 현재 orchestrator.py의 `MAX_TOOL_ROUNDS = 5` 로직은 validator_node 추가 후 **비활성화 또는 제거**한다. validator_node가 RETRY 횟수(최대 2회)를 직접 관리하며, `tool_round >= 2` 조건으로 MANUAL_REVIEW를 트리거한다. 두 로직이 동시에 존재하면 validator보다 MAX_TOOL_ROUNDS가 먼저 발동해 validator가 무의미해진다.

---

### 8.2 AgenticPay — 채팅 협상 합의 감지

**핵심**: Multi-round Negotiation + Structured Action Extraction (버튼 없이 자연어로만)

#### 전체 플로우

```
구매자 → browse에서 "견적 요청" 클릭
    ↓
채팅방 생성 + 이동
    ↓
AI가 채팅창에 견적 텍스트 자동 발송
    ↓
[멀티턴 자연어 협상]
판매자/구매자 자유 채팅
    ↓
매 메시지마다 analyze_chat_consensus 백그라운드 실행
(should_analyze 쿨다운 적용)
    ↓
case 1: consensus → 자동 주문 생성 + 캘린더 등록
                  → 채팅방: "🤖 AI가 거래 합의를 감지하여 주문을 자동 생성했습니다. (AgenticPay 논문 기반)"
case 2: negotiating → 액션 없음
case 3: rejected    → 채팅방 메시지 없음. 판매자/구매자 각자에게 개별 WebSocket으로 대체 거래처 전달
case 4: general     → 액션 없음
```

#### 쿨다운 로직 (chat_ws.py에 구현)

```python
last_analysis: dict = {}  # room_id → {"time": float, "status": str}

def should_analyze(room_id: str) -> bool:
    last = last_analysis.get(room_id)
    if not last:
        return True
    elapsed = time.time() - last["time"]
    if last["status"] == "general":
        return elapsed > 60      # 일반 대화: 60초 쿨다운
    if last["status"] == "negotiating":
        return elapsed > 10      # 협상 중: 10초마다 재확인
    return True                  # consensus/rejected: 항상 재확인
```

#### ⚠️ async/sync 충돌 주의

```python
# 잘못된 방식 (서버 블로킹)
result = find_alternative_partners(...)

# 올바른 방식
result = await asyncio.to_thread(find_alternative_partners, ...)
```

---

### 8.3 Agentic LLMs in the supply chain — 재고 타협안

**핵심**: 재고 불일치 시 이분법 거절 대신 Consensus-seeking 타협안 자동 생성

**구현 위치**: `orchestrator.py`의 `response_node` + `AGENT_SELLER/BUYER_SYSTEM` 프롬프트

**수정 포인트**:
- `response_node:772` — `last.get("message")` 있어도 재고 부족 결과면 LLM 통과
- `AGENT_SELLER_SYSTEM` — 재고 불일치 타협안 지침 추가
- `AGENT_BUYER_SYSTEM` — `find_alternative_partners`, `get_calendar_events`, `create_calendar_event` 사용 지침 추가

---

## 9. 에이전트별 상세 명세 (Few-shot 프롬프트)

### 9.1 AI 어시스턴트 오케스트레이터 (orchestrator.py)

#### 모든 입력 경우의 수

```
CASE-1:  재고 조회 → 충분         → check_stock → 답변
CASE-2:  재고 조회 → 부족         → check_stock → response_node LLM이 타협안 자동 생성
                                     담당: orchestrator.py response_node
                                     a. 분할 납품 제안
                                     b. 유사 상품 대체 제안
                                     c. "대체 거래처 탐색할까요?" (동의 후 다음 턴에 탐색)
CASE-3:  주문 조회               → get_orders / get_order_detail
CASE-4:  주문 생성               → create_order 성공 → create_calendar_event 즉시 자동 연쇄 호출
CASE-5:  주문 상태 변경          → update_order_status
CASE-6:  캘린더 일정 조회        → get_calendar_events
CASE-7:  캘린더 일정 등록        → (중복 확인 후) create_calendar_event
CASE-8:  대체 거래처 탐색        → find_alternative_partners → LLM이 추천 순위 판단
CASE-9:  상품 CRUD              → create/update/delete_product
CASE-10: 일반 질문              → GENERAL intent → response_node 직행
```

#### Few-shot 프롬프트 (AGENT_SELLER_SYSTEM / AGENT_BUYER_SYSTEM에 추가)

```python
FEW_SHOT_EXAMPLES = """
[재고 충분]
사용자: 사과 재고 얼마나 있어?
에이전트: (check_stock 후) 현재 사과 후지 재고는 150박스입니다. 상태는 정상(NORMAL)입니다.

[재고 부족 — 타협안 자동 생성]
사용자: 사과 200박스 납품 가능해?
에이전트: (check_stock → 80박스 확인)
현재 사과 후지 재고는 80박스로 요청 수량(200박스)에 부족합니다.
아래 방안을 검토해 드릴까요?
- 분할 납품: 80박스 이번 주 즉시 출하, 나머지 120박스는 다음 주 입고 후 납품
- 대체 상품: 사과 홍로 (재고 210박스, 단가 유사)로 대체
- 대체 거래처 탐색: 과거 거래 이력 기반 공급처를 찾아드릴까요?

[대체 거래처 탐색]
사용자: 대체 거래처 찾아줘
에이전트: (find_alternative_partners 호출, LLM이 추천 순위 판단)
상황에 맞는 추천 거래처를 찾았습니다:
1. 한라농산 (거래 12회, 사과 전문, 현재 재고 300박스)
2. 제주청과 (거래 8회, 유사 단가, 재고 150박스)

[주문 생성 후 캘린더 자동 등록]
사용자: 김철수마트에 배추 100박스 주문, 납품일 4월 15일
에이전트: (create_order → create_calendar_event 자동 연쇄)
주문이 생성됐습니다. 납품 일정도 캘린더에 자동 등록했습니다: [4월 15일 - 배추 100박스 납품]

[자연어 일정 등록]
사용자: 다음주 화요일에 한라마트 미팅 있어
에이전트: (get_calendar_events 중복 확인 → create_calendar_event)
4월 15일(화) 한라마트 미팅 일정을 등록했습니다.

[일반 질문]
사용자: 요즘 사과 시세 어때?
에이전트: 저는 AgriFlow 플랫폼 내 데이터만 조회 가능합니다.
현재 등록하신 사과 상품의 단가를 확인해 드릴까요?
"""
```

---

### 9.2 채팅 합의 감지 에이전트 (agent_tools.py + chat_ws.py)

#### analyze_chat_consensus 프롬프트

```python
CONSENSUS_SYSTEM_PROMPT = """
당신은 농산물 B2B 거래 채팅의 협상 분석 에이전트입니다.
최근 대화를 분석하여 거래 합의 여부와 상태를 JSON으로 반환하십시오.

⚠️ AgenticPay 논문(Structured Action Extraction) 기반 구현.
합의 감지 시 프론트엔드 채팅방에 "AI가 거래 합의를 감지했습니다 (AgenticPay 기반)" 시스템 메시지 표시.

[분류 기준]
- "consensus": 가격, 수량, 납기일 세 가지가 모두 명확히 합의된 경우
  (하나라도 null이면 confidence 낮게 — 단, confidence 무관하게 자동 주문 생성)
- "negotiating": 협상 진행 중
- "rejected": 한쪽이 명확히 거절 또는 협상 종료 의사 표명
- "general": 거래 무관 일상 대화

[합의 표현] "좋습니다", "확인했습니다", "진행하겠습니다", "네 그렇게 하죠", "알겠습니다"
[거절 표현] "어렵겠습니다", "다음에", "조건이 안 맞네요", "힘들 것 같습니다"

[Few-shot 예시 1 — consensus]
대화: 구매자: 사과 100박스 3,000원? / 판매자: 네 가능합니다 / 구매자: 4월 20일 납품 / 판매자: 확인했습니다
반환: {"status":"consensus","confidence":0.97,"extracted":{"product":"사과 후지","quantity":100,"unit":"box","price_per_unit":3000,"delivery_date":"2026-04-20"}}

[Few-shot 예시 2 — consensus 낮음]
대화: 구매자: 배추 좀 보내주세요, 2,500원이요 / 판매자: 네 알겠습니다
반환: {"status":"consensus","confidence":0.61,"extracted":{"product":"배추","quantity":null,"unit":null,"price_per_unit":2500,"delivery_date":null}}

[Few-shot 예시 3 — negotiating]
대화: 구매자: 딸기 50박스? / 판매자: 8,000원입니다 / 구매자: 7,500원은?
반환: {"status":"negotiating","confidence":null,"extracted":{}}

[Few-shot 예시 4 — rejected]
대화: 구매자: 감자 200박스 이번 주? / 판매자: 재고 없어서 어렵겠습니다
반환: {"status":"rejected","confidence":null,"extracted":{"product":"감자","rejection_reason":"재고 없음"}}

[Few-shot 예시 5 — general]
대화: 판매자: 오늘 날씨 좋네요 / 구매자: 그러게요
반환: {"status":"general","confidence":null,"extracted":{}}

반드시 위 JSON 형식으로만 반환. 다른 텍스트 포함 금지.
"""
```

---

### 9.3 캘린더/일정 에이전트 (schedule_agent.py)

**현재 상태**: ✅ 완전 구현됨.
- SELLER/BUYER 프롬프트 분리 (`_build_system_prompt` L111~153)
- 데이터 분기 (`build_schedule_context` L42~84)
- JSON 강제 (`response_format={"type": "json_object"}` L242)

**유일한 수정 사항**: BUG-1 — `schedule_agent.py:47, 59, 80` `.is_("deleted_at", "null")` → `.is_("deleted_at", None)`

**고도화 옵션** (구현 필수 아님): 현재 프롬프트 기본 분석 수준. 아래 EOQ/Bullwhip 개념을 시스템 프롬프트에 추가하면 추천 품질 향상 가능.

```python
# schedule_agent.py _build_system_prompt 고도화 추가 내용
"""
[논문 기반 핵심 원칙]
1. EOQ(경제적 주문 수량): 주문 비용과 재고 유지 비용의 균형점에서 발주 수량 산정
2. Bullwhip 효과 최소화: 수요 변동이 클수록 소량 다빈도 납품으로 리스크 분산
3. 재고 부족 시 단순 "불가" 대신 분할 납품 제안

[SELLER 경우의 수]
CASE-1: 재고 정상, 기존 출하 일정 있음 → 기존 패턴 기반 다음 출하 일정 추천
CASE-2: 재고 부족 (LOW_STOCK/OUT_OF_STOCK) → 긴급 발주 + 분할 납품 (EOQ 기반)
CASE-3: 주문 급증 감지 (Bullwhip 경보) → 수요 급변 경고 + 분산 납품 추천
CASE-4: 일정 없음 (신규 판매자) → 기본 출하 주기 가이드

[BUYER 경우의 수]
CASE-1: 납품 예정 주문 있음 → 납품 수령 + 검수 일정 추천
CASE-2: 주문 없음 / 재고 소진 임박 → 발주 시점 추천 (EOQ 기반)
CASE-3: 납품 집중 (Bullwhip 경보) → 납품 분산 수령 제안
"""
```

---

### 9.4 Validator 노드 (orchestrator.py 신규)

#### 처리 경우의 수

```
CASE-1: success=True                    → PASSED → response_node
CASE-2: success=False, tool_round < 2   → RETRY → orchestrator_node 복귀
CASE-3: success=False, tool_round >= 2  → FAILED, tag="MANUAL_REVIEW" → response_node
CASE-4: 논리적 이상 (음수 재고 등)      → FAILED, tag="DATA_ANOMALY" → response_node
```

#### Validator 프롬프트

```python
VALIDATOR_SYSTEM_PROMPT = """
당신은 AgriFlow AI 에이전트의 검증자입니다.
tool 실행 결과의 사실 여부와 논리적 오류를 검사하고 JSON으로 판정을 반환합니다.

[검증 항목]
1. success 여부
2. 반환 데이터 논리적 타당성 (음수 재고, 과거 납기일 등)
3. 필수 필드 누락

예시 1: {"validation":"PASSED","issues":[]}
예시 2: {"validation":"RETRY","issues":["상품 조회 실패 — product_name 파라미터 재확인 필요"]}
예시 3: {"validation":"FAILED","issues":["DB 오류 반복"],"tag":"MANUAL_REVIEW"}
예시 4: {"validation":"FAILED","issues":["재고 수량 음수(-30)"],"tag":"DATA_ANOMALY"}
"""
```

---

## 9.5 논문 구현 현황 및 미구현 상세

> AgriFlow는 3개 논문의 핵심 아이디어를 실제 B2B 플랫폼에 적용한다.

### 논문 1: AgenticPay — Multi-round Negotiation & Structured Action Extraction

| 논문 핵심 개념 | 구현 상태 | 구현 위치 |
|--------------|---------|---------|
| 버튼 없이 자연어로만 거래 합의 | ✅ 설계됨 | chat_ws.py + analyze_chat_consensus |
| Structured Action Extraction (JSON 추출) | ✅ 프롬프트 설계됨 | CONSENSUS_SYSTEM_PROMPT (섹션 9.2) |
| 합의 감지 → 자동 주문 생성 | ❌ 미구현 | chat_ws.py case 1 |
| 협상 결렬 → 대체 거래처 개별 안내 | ❌ 미구현 | chat_ws.py case 3 + send_private_message |
| 다중 라운드 쿨다운 관리 | ❌ 미구현 | chat_ws.py should_analyze |
| **논문에서 더 구현 가능한 부분** | | |
| Commitment Tracking: 각 메시지에서 "약속/철회" 상태 누적 추적 | ⬜ 미착수 | analyze_chat_consensus 확장 가능 |
| Anchor Price 감지: 첫 제시 가격이 협상 기준점이 되는 패턴 | ⬜ 미착수 | CONSENSUS_SYSTEM_PROMPT에 추가 가능 |

### 논문 2: AgentOrchestra — TEA Protocol (Analyzer-Executor-Validator)

| 논문 핵심 개념 | 구현 상태 | 구현 위치 |
|--------------|---------|---------|
| Analyzer 노드 (intent 분류) | ✅ 구현됨 | orchestrator_node |
| Executor 노드 (tool 실행) | ✅ 구현됨 | inventory_order_node |
| Validator 노드 (결과 검증) | ❌ 미구현 | orchestrator.py 신규 노드 추가 필요 |
| RETRY 루프 (최대 2회) | ❌ 미구현 | validator_node → orchestrator_node 엣지 |
| MANUAL_REVIEW/DATA_ANOMALY 태그 | ❌ 미구현 | validator_node 출력 + 프론트 배너 |
| **논문에서 더 구현 가능한 부분** | | |
| Role-based Tool Access: 역할별 도구 접근 제한 (SELLER는 buyer 도구 호출 불가) | ⬜ 미착수 | orchestrator_node 권한 체크 강화 |
| Cross-agent Communication: 여러 에이전트가 공유 메모리로 협업 | ⬜ 미착수 | AgentState에 shared_context 필드 추가 |

### 논문 3: Agentic LLMs in Supply Chain — EOQ / Bullwhip / Consensus-seeking

| 논문 핵심 개념 | 구현 상태 | 구현 위치 |
|--------------|---------|---------|
| Consensus-seeking 타협안 (분할납품/대체상품) | ❌ 미구현 (프롬프트 추가 필요) | orchestrator.py response_node |
| EOQ 기반 발주 수량 추천 | ✅ schedule_agent.py 프롬프트 설계됨 | schedule_agent.py (고도화 옵션) |
| Bullwhip 효과 경보 | ✅ schedule_agent.py 프롬프트 설계됨 | schedule_agent.py (고도화 옵션) |
| **논문에서 더 구현 가능한 부분** | | |
| Demand Forecasting: 주문 이력 기반 수요 예측 (LLM + 통계) | ⬜ 미착수 | 신규 `forecast_demand` tool 추가 가능 |
| Multi-tier Supply Chain: 도매상 → 소매상 → 최종구매자 다단계 추적 | ⬜ 미착수 | 현재 2-tier(판매자-구매자)만 구현됨 |

### 구현 우선순위 (논문 관점)

```
즉시 필수: AgentOrchestra validator_node, AgenticPay chat_ws 4분기
선택적 강화: Commitment Tracking, Role-based Tool Access, Demand Forecasting
미착수 고급: Cross-agent Communication, Multi-tier Supply Chain
```

---

## 10. 예외 처리 및 보안 가이드

### 10.1 권한 체크

```
[권한 원칙 — AGENT_SELLER/BUYER_SYSTEM 프롬프트에 포함]
- 주문 상태 변경: 해당 주문의 seller_id 또는 buyer_id == 현재 user_id
- 상품 삭제/수정: 해당 상품의 seller_id == 현재 user_id
- 권한 불일치 명확 시 tool 호출 전 즉시 거절
```

### 10.2 상품명 모호성 처리

| 작업 | 처리 방식 |
|------|---------|
| 조회 (재고 확인, 검색) | LLM이 가장 유사한 상품 자동 선택 |
| **삭제 / 수정** | 전체 목록 보여주고 사용자 직접 선택 유도 |

### 10.3 일정 중복 확인

`create_calendar_event` 호출 전 동일 날짜 일정 존재 시 확인 후 진행.

### 10.4 find_alternative_partners 추천 순위

DB 결과를 LLM에게 넘겨 상황(재고 없음/협상 결렬/직접 요청)에 맞게 LLM이 직접 추천 순위와 이유 생성. 단순 정렬 공식 사용 금지.

### 10.5 connection_manager.py 개별 전송 추가

```python
# 추가 구현 (connection_manager.py)
active_user_connections: dict[str, WebSocket] = {}

async def connect(self, websocket: WebSocket, room_id: str, user_id: str):
    # 기존 room_id 등록 + user_id 개별 매핑 추가
    self.active_user_connections[user_id] = websocket

async def send_private_message(self, user_id: str, message: dict):
    ws = self.active_user_connections.get(user_id)
    if ws:
        await ws.send_json(message)
```

### 10.6 구매자 browse → 채팅 견적 플로우

1. "견적 요청" 클릭 → `POST /chat/rooms` 채팅방 생성
2. 채팅 페이지로 이동
3. AI가 채팅창에 견적 텍스트 자동 발송 (텍스트 형식, 별도 DB 컬럼 추가 불필요)
4. 판매자 자연어 응답 → 멀티턴 협상 → `analyze_chat_consensus` 모니터링
