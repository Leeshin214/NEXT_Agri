# Claude Code 프롬프트 사용 가이드

## 파일 구조

```
프로젝트 루트/
├── CLAUDE.md              ← 반드시 프로젝트 루트에 위치
├── SKILL_DB.md
├── SKILL_API.md
├── SKILL_FRONTEND.md
├── SKILL_AUTH.md
├── SKILL_CHAT.md
├── SKILL_AI.md
├── SKILL_TEST.md
├── frontend/
└── backend/
```

---

## 초기 설정 (첫 번째 프롬프트)

Claude Code를 처음 열었을 때, 아래 프롬프트를 입력한다:

```
CLAUDE.md 파일을 읽고 프로젝트 전체 구조를 파악해라.
이 프로젝트는 농산물 유통 B2B 플랫폼 AgriFlow이다.
앞으로 모든 작업은 CLAUDE.md의 컨벤션을 따른다.
```

---

## Phase별 프롬프트

---

### Phase 1: DB 스키마 설정

```
SKILL_DB.md를 읽고 아래 작업을 순서대로 진행해라.

1. supabase/migrations/ 디렉토리를 생성해라
2. SKILL_DB.md에 정의된 모든 테이블의 마이그레이션 SQL 파일을 생성해라
   - 파일명: YYYYMMDDHHMMSS_{테이블명}.sql 형식
   - 순서: users → products → partners → orders → order_items → calendar_events → chat_rooms → messages → ai_conversations
3. updated_at 자동 갱신 트리거를 모든 테이블에 적용해라
4. 모든 테이블에 RLS 정책을 설정해라 (SKILL_DB.md의 RLS 예시 참고)
5. 인덱스 파일을 별도로 생성해라
6. supabase/seed.sql을 생성해라 (한국 농산물 유통 문맥의 현실적인 테스트 데이터)
   - 판매자 2명, 구매자 2명
   - 상품 7개 (사과, 배, 딸기, 토마토, 양파, 감자, 쌀)
   - 주문 5건 (다양한 상태)
   - 채팅방 2개 + 메시지 10개
7. 각 파일을 생성한 후 내용을 확인하고 문제가 없는지 검토해라
```

---

### Phase 2: 인증 시스템

```
SKILL_AUTH.md를 읽고 인증 시스템을 구현해라.

[Backend]
1. backend/ 디렉토리 구조를 생성해라 (CLAUDE.md 구조 참고)
2. requirements.txt를 생성해라 (SKILL_API.md 참고)
3. app/core/config.py - pydantic-settings 설정
4. app/core/security.py - Supabase JWT 검증 함수
5. app/core/supabase.py - Supabase admin client 설정

[Frontend]
6. frontend/ Next.js 14 프로젝트를 초기화해라
   명령: npx create-next-app@latest frontend --typescript --tailwind --app
7. 필요한 패키지를 설치해라 (SKILL_FRONTEND.md 참고)
8. src/lib/supabase/client.ts, server.ts 생성
9. src/middleware.ts - 라우트 보호 + 역할 기반 리다이렉트
10. src/store/authStore.ts - Zustand auth store
11. src/hooks/useAuth.ts
12. app/(auth)/login/page.tsx - 로그인 UI
13. app/(auth)/register/page.tsx - 회원가입 UI (역할 선택 포함)

[Supabase]
14. supabase/migrations/에 auth trigger SQL 추가 (SKILL_AUTH.md 참고)
```

---

### Phase 3: FastAPI 기본 구조 + 핵심 API

```
SKILL_API.md를 읽고 FastAPI 백엔드를 구현해라.

1. app/main.py - FastAPI 앱 + CORS 설정
2. app/models/ - SQLAlchemy 모델 전체 (CLAUDE.md 스키마 기반)
   - base.py, user.py, product.py, order.py, partner.py, calendar.py, chat.py
3. app/schemas/ - Pydantic v2 스키마
   - common.py (SuccessResponse, PaginationMeta)
   - 각 도메인별 Request/Response 스키마
4. app/dependencies.py - get_current_user, get_db, require_role
5. app/api/v1/ 라우터 파일 생성:
   - products.py (CRUD + 판매자 필터)
   - orders.py (생성, 상태 변경, 목록)
   - partners.py (거래처 목록, 추가, 수정)
   - calendar.py (이벤트 CRUD)
6. app/api/router.py - 라우터 통합
7. app/core/exceptions.py - 에러 핸들러

각 엔드포인트는 SKILL_API.md의 표준 응답 포맷을 따를 것.
```

---

### Phase 4: Frontend 레이아웃 + 공통 컴포넌트

```
SKILL_FRONTEND.md를 읽고 프론트엔드 공통 구조를 구현해라.

1. tailwind.config.ts - 농산물 플랫폼 색상 테마 적용 (primary: 초록 계열)
2. src/types/ - 모든 TypeScript 타입 파일 생성 (SKILL_FRONTEND.md 참고)
3. src/constants/menus.ts - 판매자/구매자 사이드바 메뉴 정의
4. src/constants/options.ts - 상태값, 카테고리, 단위 옵션
5. src/lib/api.ts - FastAPI 호출 wrapper
6. src/components/layout/
   - AppLayout.tsx
   - TopBar.tsx (서비스명, 검색창, 알림, 프로필)
   - Sidebar.tsx (역할별 메뉴, 활성 메뉴 표시)
7. src/components/common/
   - StatusBadge.tsx
   - SummaryCard.tsx
   - DataTable.tsx
   - SearchFilterBar.tsx
   - PageHeader.tsx
   - EmptyState.tsx
   - Modal.tsx
8. app/layout.tsx - 최상위 레이아웃 (QueryClient provider 포함)
9. app/(dashboard)/layout.tsx - AppLayout 적용
10. app/page.tsx - 역할 선택 랜딩 페이지

디자인 기준:
- 배경: bg-gray-50, 카드: bg-white rounded-xl shadow-sm
- 포인트: primary-600 (#16a34a)
- 판매자/구매자 랜딩은 충분히 설득력 있게 디자인
```

---

### Phase 5: 판매자 페이지 구현

```
SKILL_FRONTEND.md를 읽고 판매자 7개 페이지를 구현해라.
각 페이지는 실제 업무툴처럼 보여야 하며, React Query로 API를 호출한다.
API가 아직 없는 경우 mock 데이터를 사용해도 된다.

1. app/(dashboard)/seller/dashboard/page.tsx
   - SummaryCard 4개 (오늘 출하, 신규 견적, 미확인 채팅, 재고부족)
   - 최근 주문 5건 테이블
   - 이번 주 출하 일정 카드
   - 빠른 작업 버튼 4개

2. app/(dashboard)/seller/calendar/page.tsx
   - 월간 달력 UI (이벤트 표시)
   - 날짜 클릭 → 우측 패널에 일정 상세
   - 이벤트 타입별 색상 구분

3. app/(dashboard)/seller/partners/page.tsx
   - 거래처 테이블 (검색/필터)
   - 행 클릭 → 우측 슬라이드 패널

4. app/(dashboard)/seller/products/page.tsx
   - 상품 목록 테이블 (상태 필터)
   - 상품 등록 버튼 → 모달 폼

5. app/(dashboard)/seller/orders/page.tsx
   - 탭: 견적요청 | 진행중 | 완료
   - 주문 상세 패널

6. app/(dashboard)/seller/chat/page.tsx
   - 좌측 채팅방 목록
   - 우측 채팅 창

7. app/(dashboard)/seller/ai-assistant/page.tsx
   - 빠른 프롬프트 4개
   - 스트리밍 응답 패널
   - 입력창
```

---

### Phase 6: 구매자 페이지 구현

```
판매자 페이지와 같은 방식으로 구매자 7개 페이지를 구현해라.
판매자와 달라야 하는 부분:

1. buyer/dashboard: 납품 일정, 관심 품목 가격 요약 카드
2. buyer/browse: 농산물 카드 탐색 (카테고리 필터, 견적 요청 버튼)
3. buyer/ai-assistant: 구매자 관점 프롬프트 (납품 일정, 단가 비교 등)

나머지는 구조는 동일하되 데이터와 레이블을 구매자 관점으로 변경해라.
```

---

### Phase 7: 채팅 기능 구현

```
SKILL_CHAT.md를 읽고 실시간 채팅을 구현해라.

1. Supabase realtime publication SQL 설정
2. FastAPI chat 라우터 구현 (rooms, messages CRUD)
3. src/hooks/useChat.ts - 메시지 조회 + Supabase Realtime 구독
4. src/components/chat/ChatRoomList.tsx
5. src/components/chat/ChatWindow.tsx (스크롤 자동, 전송)
6. 읽음 처리 로직
7. 안읽은 메시지 수 뱃지
8. AI 요약 버튼 (채팅 내용 요약 API 연동)
```

---

### Phase 8: AI 도우미 구현

```
SKILL_AI.md를 읽고 AI 업무 도우미를 구현해라.

1. FastAPI ai_assistant.py 라우터
   - POST /ai/chat (스트리밍)
   - POST /ai/summarize-chat
2. 판매자/구매자 각 System Prompt 작성
3. 사용자 컨텍스트 빌더 (오늘 일정, 재고, 미결 주문 등 DB 조회)
4. src/hooks/useAIStream.ts - SSE 파싱 훅
5. src/constants/aiPrompts.ts - 빠른 프롬프트 정의
6. src/components/ai/AIResponsePanel.tsx - 마크다운 렌더링 포함
```

---

### Phase 9: 테스트

```
SKILL_TEST.md를 읽고 테스트를 작성해라.

Backend:
1. pytest conftest.py 설정
2. test_products.py - CRUD + 권한 테스트
3. test_orders.py - 상태 플로우 테스트
4. test_auth.py - JWT 검증, 역할 체크

Frontend:
1. Vitest 설정
2. StatusBadge, SummaryCard 컴포넌트 테스트
3. useAIStream 훅 테스트
```

---

## 개별 작업 프롬프트 예시

### 특정 파일 수정
```
backend/app/api/v1/products.py의 list_products 엔드포인트에
카테고리별 필터링 기능을 추가해라.
SKILL_API.md의 표준 응답 포맷을 따를 것.
```

### 버그 수정
```
seller/products 페이지에서 상품 등록 모달을 제출했을 때
목록이 즉시 갱신되지 않는 문제를 수정해라.
React Query의 invalidateQueries를 사용할 것.
```

### 컴포넌트 추가
```
SKILL_FRONTEND.md를 참고해서
src/components/common/ConfirmDialog.tsx를 만들어라.
삭제 확인 등에 사용할 재사용 가능한 다이얼로그.
```

---

## 주의사항

1. **CLAUDE.md 항상 참조**: 모든 작업 전에 CLAUDE.md를 확인해서 컨벤션을 지킬 것
2. **SKILL 파일 먼저 읽기**: 각 Phase 작업 전에 해당 SKILL 파일을 읽어라
3. **단계별 진행**: Phase를 건너뛰지 말 것 (특히 DB → Auth → API 순서)
4. **환경변수 하드코딩 금지**: 모든 비밀값은 .env에 넣을 것
5. **타입 any 금지**: TypeScript strict mode, any 사용 불가
6. **RLS 필수**: 모든 DB 작업 후 RLS 정책 확인
