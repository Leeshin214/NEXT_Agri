# CLAUDE.md — 농산물 유통 B2B AI 플랫폼 (AgriFlow)

## 작업 처리 원칙

- **코드 수정/구현 요청**: 복잡도/난이도 무관하게 무조건 sub-agent에 위임 (frontend-agent, backend-agent, ai-agent)
- **일반 질문**: Claude가 직접 처리 (코드 설명, 구조 질문, 상태 확인 등)
- 단 한 줄 수정이라도 코드를 건드리면 agent를 호출한다

### 코드 검증 워크플로우 (필수)

**코드를 수정하는 모든 작업에서 아래 흐름을 반드시 따른다.**

```
1. 개발 agent 실행 (frontend-agent / backend-agent / ai-agent)
   ↓
2. validator-agent 실행 (개발 agent 완료 직후 항상 실행)
   ↓
3A. VALIDATION_PASSED → 4단계로 진행
3B. VALIDATION_FAILED → 리포트의 "수정 필요 agent 목록" 을 보고
                        해당 agent에 수정 지시 → 2번으로 돌아감
                        (최대 3회 재시도, 이후에도 실패 시 사용자에게 오류 상황 보고)
   ↓
4. QA Tester 게이트 (자율 PM 사이클일 때만 적용)
   - 사용자가 "사이클 시작해" / "PM 작업 진행해줘" 같은 자율 사이클 모드일 때만 진입
   - 단발 요청(예: "이 버그 고쳐줘")은 4단계 건너뛰고 사용자에게 답변
   - 컨텍스트 사용량(`/context` 또는 추정)이 50% 미만이면 qa-tester-agent 실행
   - QA_PASSED → commit + push + 사용자에게 결과 보고
   - QA_FAILED → 발견 이슈를 적절한 agent(frontend/backend)에 수정 위임 → 1단계로 돌아감
                 (최대 2회 QA 재실행, 이후에도 실패하면 이슈를 다음 PM 사이클로 이월하고 종료)
   - QA_BLOCKED → dev server 시작 후 재시도 또는 사용자에게 보고
```

- validator-agent는 TypeScript 컴파일, Python 문법, 프론트↔백 API 계약 불일치, 타입 불일치를 검사한다
- qa-tester-agent는 실제 브라우저로 사용자 시나리오를 진행하며 UX 페인 포인트·런타임 버그를 발견한다 (코드 미수정)
- 사용자에게 답변할 때는 반드시 `VALIDATION_PASSED` 상태에서만 답변한다 (QA는 자율 사이클일 때만 추가 게이트)

### 자율 사이클 식별

다음 상황을 "자율 사이클"로 본다:
- 사용자가 GitHub Issue (`pm-cycle` 라벨)의 PM Report 작업을 진행하라고 명시한 경우
- 사용자가 "사이클 시작해", "다음 PM 작업 진행해줘" 같은 자율 모드 명령을 내린 경우
- 그 외 단발 작업·디버깅·질문·정보 조회는 자율 사이클이 아님 → QA tester 미실행

---

### 자율 사이클 트리거 (필수 자동 수행 절차)

사용자가 **"사이클 실행해" / "사이클 시작해" / "PM 알림 왔어 진행해줘" / "최신 PM 이슈 작업 진행"** 등으로 자율 사이클을 트리거하면, **gh CLI 인증을 시도하지 말고 public API로 즉시 다음 흐름을 끝까지 자동 진행한다.** 사용자에게 추가 확인을 묻지 않는다 (Low 위험도 작업은 자동 진행이 정책).

```bash
# Step 1 — 워킹트리 정리 (빌드 산출물 등 noise 제거)
git restore frontend/tsconfig.tsbuildinfo 2>/dev/null || true

# Step 2 — caffeinate 백그라운드 시작 (4시간 sleep 차단)
caffeinate -i -t 14400 &
disown

# Step 3 — 최신 PM Report 이슈 조회 (gh CLI 인증 불필요, public API)
curl -s "https://api.github.com/repos/Leeshin214/NEXT_Agri/issues?labels=pm-cycle&state=open&per_page=1&sort=created&direction=desc"
```

응답 JSON에서 `body` 필드를 파싱하여 다음 처리:

1. **위험도 Low 작업 추출** — `[Low]` 표시된 추천 작업 모두 자동 진행 대상
2. **위험도 High 작업 보류** — 진행하지 않고 사이클 끝에 별도 항목으로 사용자에게 보고만
3. **개발 위임** — 적절한 sub-agent (frontend-agent / backend-agent / ai-agent) 분배
4. **검증** — validator-agent (VALIDATION_PASSED 까지 최대 3회 재시도)
5. **QA** — qa-tester-agent (자율 사이클이므로 실행, 최대 2회 재시도)
   - dev server 가 안 떠 있으면 backend(uvicorn) + frontend(npm run dev) 백그라운드로 시작 후 QA 진행
6. **commit + push** — dev 브랜치에 변경사항 push
7. **caffeinate 종료** — `pkill -x caffeinate`
8. **최종 요약 보고**:
   - 진행된 작업 목록
   - QA 발견 이슈 + 수정 결과
   - High 위험도 보류 항목 (사용자 검토 필요)
   - 다음 사이클 권장사항 (있으면)

### 자율 사이클 중 사용자 개입 금지 사항

- gh CLI 인증 묻지 않기 (public API 사용)
- "어느 작업을 진행할까요?" 묻지 않기 (위험도 Low 자동 진행 정책)
- VALIDATION_FAILED 시 사용자에게 묻지 말고 자동 재시도 (최대 3회)
- QA_FAILED 시 사용자에게 묻지 말고 자동 수정 위임 (최대 2회)
- High 위험도 작업은 진행하지 않고 보류 — 묻지 말고 그냥 보류 후 보고만

사용자 개입이 필요한 케이스 (이때만 멈추고 보고):
- VALIDATION 3회 재시도 후에도 실패
- QA 2회 재시도 후에도 실패 (단 QA_BLOCKED는 아래 자동 처리)
- public API 응답이 비어있거나 이슈 없음

### QA Tester 동작 방식

`qa-tester-agent` 는 **브라우저 자동화를 사용하지 않고 코드 정적 분석으로만** QA 를 진행한다 (시간 비용·환경 의존성 최소화). 1-2분 안에 변경 영역의 잠재 버그·UX 페인 포인트를 식별해 리포트만 반환하고, 수정은 메인이 frontend/backend-agent 에 분배한다.

QA 결과는 두 가지:
- **QA_PASSED** → commit + push 진행
- **QA_FAILED** → 메인이 발견 이슈를 적절 agent 에 수정 위임 → validator → 다시 QA (최대 2회 재시도)
  - Critical 이슈 → 즉시 수정
  - Major/Minor 만 → 현재 사이클 commit 진행 + 다음 PM 사이클 후보로 기록

코드만 읽으므로 dev server 나 브라우저가 없어도 동작한다. `QA_BLOCKED` 는 일반적으로 발생하지 않는다 (Read/Grep/Bash 만 의존). 만에 하나 발생하면 사이클 commit 진행 후 다음 사이클로 검증 이월.

---

## 프로젝트 개요

**서비스명**: AgriFlow  
**목적**: 농산물 유통업 판매자(공급자)와 구매자(바이어)를 연결하는 B2B 업무 웹플랫폼  
**핵심 기능**: 거래처 관리, 주문/견적, 재고/출하, 채팅, AI 업무 보조

---

## 기술 스택

### Frontend
- **Framework**: Next.js 14 (App Router)
- **Language**: TypeScript (strict mode)
- **Styling**: Tailwind CSS v3
- **State**: Zustand (전역), React Query (서버 상태)
- **Form**: React Hook Form + Zod
- **Chart**: Recharts
- **Icons**: Lucide React

### Backend
- **Framework**: FastAPI (Python 3.11+)
- **Auth**: Supabase Auth (JWT)
- **ORM**: SQLAlchemy + asyncpg
- **Validation**: Pydantic v2
- **WebSocket**: FastAPI WebSocket (채팅)
- **Background**: Celery + Redis (알림, 배치)
- **AI**: OpenAI API (gpt-4o-mini)

### Database / Infra
- **Database**: Supabase (PostgreSQL 15)
- **Storage**: Supabase Storage (상품 이미지)
- **Realtime**: Supabase Realtime (채팅, 알림)
- **Cache**: Redis
- **Deploy**: Vercel (FE) + Railway/Fly.io (BE)

---

## 프로젝트 디렉토리 구조

```
agriflow/
├── frontend/                    # Next.js 14 App
│   ├── app/
│   │   ├── (auth)/
│   │   │   ├── login/
│   │   │   └── register/
│   │   ├── (dashboard)/
│   │   │   ├── seller/          # 판매자 페이지
│   │   │   │   ├── dashboard/
│   │   │   │   ├── calendar/
│   │   │   │   ├── partners/
│   │   │   │   ├── products/
│   │   │   │   ├── orders/
│   │   │   │   ├── chat/
│   │   │   │   └── ai-assistant/
│   │   │   └── buyer/           # 구매자 페이지
│   │   │       ├── dashboard/
│   │   │       ├── calendar/
│   │   │       ├── partners/
│   │   │       ├── browse/
│   │   │       ├── orders/
│   │   │       ├── chat/
│   │   │       └── ai-assistant/
│   │   ├── layout.tsx
│   │   └── page.tsx             # 역할 선택 랜딩
│   ├── components/
│   │   ├── common/              # 공통 컴포넌트
│   │   ├── layout/              # AppLayout, TopBar, Sidebar
│   │   ├── seller/              # 판매자 전용
│   │   └── buyer/               # 구매자 전용
│   ├── hooks/                   # 커스텀 훅
│   ├── lib/                     # supabase client, utils
│   ├── store/                   # Zustand stores
│   ├── types/                   # TypeScript 타입 정의
│   └── constants/               # 상수, 메뉴 구조
│
├── backend/                     # FastAPI App
│   ├── app/
│   │   ├── api/
│   │   │   ├── v1/
│   │   │   │   ├── auth.py
│   │   │   │   ├── users.py
│   │   │   │   ├── products.py
│   │   │   │   ├── orders.py
│   │   │   │   ├── partners.py
│   │   │   │   ├── chat.py
│   │   │   │   ├── calendar.py
│   │   │   │   └── ai_assistant.py
│   │   │   └── router.py
│   │   ├── core/
│   │   │   ├── config.py
│   │   │   ├── security.py
│   │   │   └── supabase.py
│   │   ├── models/              # SQLAlchemy models
│   │   ├── schemas/             # Pydantic schemas
│   │   ├── services/            # 비즈니스 로직
│   │   ├── websocket/           # 채팅 WebSocket
│   │   └── main.py
│   ├── migrations/              # Alembic
│   ├── tests/
│   └── requirements.txt
│
└── supabase/
    ├── migrations/              # SQL 마이그레이션
    ├── seed.sql                 # 초기 데이터
    └── config.toml
```

---

## 역할 시스템

### 사용자 역할 (Role)
```
SELLER   - 판매자 (농가, 도매상, 유통업체)
BUYER    - 구매자 (마트, 식자재, 식당)
ADMIN    - 관리자
```

### 역할별 접근 경로
- 판매자: `/seller/*`
- 구매자: `/buyer/*`
- 공통: `/chat`, `/profile`

---

## 도메인 핵심 개념

### 상품 (Product)
- 품목: 사과, 배, 딸기, 토마토, 양파, 감자, 쌀 등
- 상태: `NORMAL` | `LOW_STOCK` | `OUT_OF_STOCK` | `SCHEDULED`
- 단위: `kg` | `box` | `개` | `포대`

### 주문/견적 (Order/Quote)
- 상태 플로우: `QUOTE_REQUESTED` → `NEGOTIATING` → `CONFIRMED` → `PREPARING` → `SHIPPING` → `COMPLETED`
- 취소: `CANCELLED`

### 거래처 (Partner)
- 판매자의 거래처 = 구매자 (바이어)
- 구매자의 거래처 = 판매자 (공급처)
- 관계 상태: `ACTIVE` | `INACTIVE` | `PENDING`

### 일정 (Calendar Event)
- 유형: `SHIPMENT` | `DELIVERY` | `MEETING` | `QUOTE_DEADLINE` | `ORDER`

---

## 코딩 컨벤션

### TypeScript
- `strict: true` 필수
- 모든 API 응답 타입 명시
- `any` 사용 금지 → `unknown` 사용 후 타입 가드
- Interface > Type (확장 가능성)

### API 설계
- RESTful: `/api/v1/{resource}`
- 페이지네이션: `?page=1&limit=20`
- 에러 응답: `{ error: string, detail?: string, code?: string }`
- 성공 응답: `{ data: T, meta?: PaginationMeta }`

### FastAPI
- 모든 엔드포인트에 `response_model` 명시
- Dependency Injection으로 인증 처리
- 비동기 (`async def`) 우선

### 데이터베이스
- 모든 테이블에 `id (UUID)`, `created_at`, `updated_at` 포함
- Soft delete: `deleted_at` 컬럼
- RLS (Row Level Security) 필수 적용

---

## 환경 변수

### Frontend (.env.local)
```
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### Backend (.env)
```
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_JWT_SECRET=
OPENAI_API_KEY=
REDIS_URL=redis://localhost:6379
DATABASE_URL=postgresql+asyncpg://...
```

---

## Sub-agent 구조

실제 sub-agent는 `.claude/agents/` 에 정의되어 있으며, Claude Code가 작업 유형에 따라 자동 위임한다.

| Agent | 파일 | 담당 범위 |
|-------|------|---------|
| frontend-agent | `.claude/agents/frontend-agent.md` | Next.js 페이지·컴포넌트, Tailwind, Zustand, 라우팅, UI 전체 |
| backend-agent | `.claude/agents/backend-agent.md` | FastAPI, SQLAlchemy, Pydantic, DB 마이그레이션, RLS, Auth |
| ai-agent | `.claude/agents/ai-agent.md` | OpenAI API 연동, 스트리밍, 프롬프트 설계, AI 기능 확장 |
| validator-agent | `.claude/agents/validator-agent.md` | 코드 수정 후 자동 검증 — TS 컴파일, Python 문법, API 계약 불일치 탐지 |
| qa-tester-agent | `.claude/agents/qa-tester-agent.md` | 자율 PM 사이클의 마지막 게이트. 실제 브라우저로 사용자 시나리오 진행, UX 페인 포인트·런타임 버그 발견 (코드 수정 X) |

### SKILL 파일 역할 (상세 스펙 문서)
각 SKILL_*.md 파일은 sub-agent가 작업 시 참조하는 상세 스펙 문서다. Agent 파일 내에서 명시적으로 참조한다.

| SKILL 파일 | 참조하는 Agent |
|-----------|--------------|
| SKILL_FRONTEND.md | frontend-agent |
| SKILL_API.md | backend-agent |
| SKILL_DB.md | backend-agent |
| SKILL_AUTH.md | frontend-agent, backend-agent |
| SKILL_CHAT.md | frontend-agent, backend-agent |
| SKILL_AI.md | ai-agent |
| SKILL_PROFILE.md | frontend-agent, backend-agent |
| SKILL_TEST.md | 필요 시 직접 참조 |

---

## 개발 순서 (권장)

1. **Phase 1**: DB 스키마 + Supabase 셋업 (`backend-agent`)
2. **Phase 2**: Auth 시스템 (`backend-agent`)
3. **Phase 3**: FastAPI 기본 구조 + 핵심 API (`backend-agent`)
4. **Phase 4**: Frontend 레이아웃 + 공통 컴포넌트 (`frontend-agent`)
5. **Phase 5**: 각 페이지 구현 (판매자 → 구매자 순) (`frontend-agent`)
6. **Phase 6**: 채팅/Realtime (`backend-agent` + `frontend-agent`)
7. **Phase 7**: AI 도우미 기능 확장 (`ai-agent`)
8. **Phase 8**: 테스트 (SKILL_TEST.md 참조)

---

## 주의사항

- Supabase RLS는 반드시 모든 테이블에 적용
- WebSocket 채팅은 Supabase Realtime 우선 검토, 복잡하면 FastAPI WebSocket
- AI 기능은 스트리밍 응답 (`streaming: true`) 사용
- 모든 금액은 원(KRW) 단위, 정수형
- 날짜/시간은 UTC 저장, 프론트에서 KST 변환
- 이미지는 Supabase Storage 사용, CDN URL 반환
