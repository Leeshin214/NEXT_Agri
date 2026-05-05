# CLAUDE.md — 농산물 유통 B2B AI 플랫폼 (AgriFlow)

## 작업 처리 원칙

- **모든 작업(코드 수정 포함)**: Claude가 직접 처리한다. sub-agent에 위임하지 않는다.
- 파일 읽기·수정·생성은 Read, Edit, Write, Bash 도구를 직접 사용한다.

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
| pm-agent | `.claude/agents/pm-agent.md` | 시니어 PM. 사용자 요청 시 호출 — README+git log+`.claude/platform-constraints.md` 종합해 User Story 형식 작업 후보 정리. 코드 미수정 |

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
