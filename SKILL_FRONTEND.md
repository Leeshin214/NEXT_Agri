# SKILL_FRONTEND.md — Frontend Agent

> **마지막 동기화**: 2026-03-22 | 실제 코드 기준으로 작성됨

## 역할
Next.js 14 (App Router) + TypeScript + Tailwind CSS로
판매자/구매자 각 페이지와 공통 컴포넌트를 구현한다.

---

## 현재 디렉토리 구조 (실제 기준)

```
frontend/
├── app/
│   ├── (auth)/
│   │   ├── login/page.tsx
│   │   └── register/page.tsx
│   └── (dashboard)/
│       ├── layout.tsx              ← AppLayout 적용
│       ├── profile/page.tsx        ← 공통 마이페이지
│       ├── seller/
│       │   ├── dashboard/page.tsx
│       │   ├── calendar/page.tsx
│       │   ├── partners/page.tsx
│       │   ├── products/page.tsx
│       │   ├── orders/page.tsx
│       │   └── chat/page.tsx       ← ai-assistant 없음 (우측 패널로 이동)
│       └── buyer/
│           ├── dashboard/page.tsx
│           ├── calendar/page.tsx
│           ├── partners/page.tsx
│           ├── browse/page.tsx
│           ├── orders/page.tsx
│           └── chat/page.tsx
├── components/
│   ├── layout/
│   │   ├── AppLayout.tsx           ← Sidebar + TopBar + main + AIChatPanel
│   │   ├── Sidebar.tsx
│   │   ├── TopBar.tsx              ← 프로필 드롭다운 포함
│   │   └── AIChatPanel.tsx         ← 우측 고정 AI 패널 (모든 페이지 공통)
│   └── common/
│       ├── PageHeader.tsx
│       ├── StatusBadge.tsx
│       ├── SummaryCard.tsx
│       ├── DataTable.tsx
│       ├── SearchFilterBar.tsx
│       ├── EmptyState.tsx
│       └── Modal.tsx
├── hooks/
│   ├── useAuth.ts
│   ├── useAIStream.ts
│   └── useChat.ts
├── store/
│   ├── authStore.ts                ← user, setUser, logout
│   └── uiStore.ts                  ← sidebarOpen, toggleSidebar
├── types/
│   ├── user.ts                     ← User, UserRole
│   └── api.ts                      ← SuccessResponse<T>, ErrorResponse
├── constants/
│   ├── menus.ts                    ← sellerMenus, buyerMenus (6개씩)
│   ├── aiPrompts.ts                ← sellerQuickPrompts, buyerQuickPrompts
│   └── options.ts
└── lib/
    ├── api.ts                      ← api.get/post/patch/delete
    └── supabase/
        ├── client.ts
        └── server.ts
```

---

## 핵심 레이아웃 구조 (중요)

```
전체 화면
├── Sidebar (좌, w-60 or w-16)
└── 우측 영역 (flex-1)
    ├── TopBar (상, h-16)
    └── 콘텐츠 영역 (flex row)
        ├── main (flex-1, min-w-0)   ← 페이지별 콘텐츠
        └── AIChatPanel (w-1/2)      ← 모든 페이지 우측 고정
```

**실제 AppLayout.tsx:**
```tsx
// frontend/components/layout/AppLayout.tsx
export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user } = useAuthStore();
  const pathname = usePathname();
  const menus = user?.role === 'SELLER' ? sellerMenus : buyerMenus;
  const isFullPage = pathname === '/profile';

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      {!isFullPage && <Sidebar menus={menus} currentPath={pathname} role={user?.role} />}
      <div className="flex flex-1 flex-col overflow-hidden">
        <TopBar user={user} />
        <div className="flex flex-1 overflow-hidden">
          <main className="flex-1 overflow-y-auto p-6 min-w-0">{children}</main>
          {!isFullPage && <AIChatPanel />}
        </div>
      </div>
    </div>
  );
}
```

---

## 사이드바 메뉴 (실제 기준 — AI 업무 도우미 없음)

```typescript
// frontend/constants/menus.ts
export const sellerMenus: MenuItem[] = [
  { label: '대시보드',       href: '/seller/dashboard', icon: LayoutDashboard },
  { label: '캘린더',         href: '/seller/calendar',  icon: Calendar },
  { label: '거래처 목록',    href: '/seller/partners',  icon: Users },
  { label: '상품/재고 관리', href: '/seller/products',  icon: Package },
  { label: '주문/견적 관리', href: '/seller/orders',    icon: ClipboardList },
  { label: '채팅',           href: '/seller/chat',      icon: MessageCircle },
  // AI 업무 도우미 없음 → AIChatPanel이 우측에 항상 고정
];

export const buyerMenus: MenuItem[] = [
  { label: '대시보드',       href: '/buyer/dashboard',  icon: LayoutDashboard },
  { label: '캘린더',         href: '/buyer/calendar',   icon: Calendar },
  { label: '거래처 목록',    href: '/buyer/partners',   icon: Users },
  { label: '상품 탐색',      href: '/buyer/browse',     icon: Search },
  { label: '주문/견적 관리', href: '/buyer/orders',     icon: ClipboardList },
  { label: '채팅',           href: '/buyer/chat',       icon: MessageCircle },
];
```

---

## TopBar — 프로필 드롭다운 (실제 기준)

```typescript
// frontend/components/layout/TopBar.tsx
// 프로필 클릭 → 드롭다운 (마이페이지 / 로그아웃)
// - 마이페이지: router.push('/profile')
// - 로그아웃: signOut()
// click-outside: useRef + mousedown 이벤트로 처리
```

---

## AIChatPanel (실제 기준)

```typescript
// frontend/components/layout/AIChatPanel.tsx
// - w-1/2 고정, border-l로 구분
// - useAuthStore로 role 감지 → sellerQuickPrompts / buyerQuickPrompts 자동 선택
// - useAIStream 훅 사용 (응답, 스트리밍 상태, 전송)
// - 입력: Enter(전송), Shift+Enter(줄바꿈) 지원
// - 별도 라우트(/ai-assistant) 없음
```

---

## 코딩 규칙

### 컴포넌트
- `'use client'`: 상태/이벤트 있으면 필수
- Props interface는 컴포넌트 파일 상단 정의
- `any` 금지 → `unknown` + 타입가드
- 파일명: PascalCase (컴포넌트), camelCase (훅/유틸)

### API 호출
```typescript
import { api } from '@/lib/api';
// 응답 타입 항상 명시
const res = await api.get<SuccessResponse<Product[]>>('/products');
// res.data로 접근 (api.ts가 자동으로 json 파싱, 에러 throw)
```

### 상태 관리
```typescript
const { user, setUser } = useAuthStore();  // user.role: 'SELLER' | 'BUYER' | 'ADMIN'
const { sidebarOpen, toggleSidebar } = useUIStore();
```

### Tailwind 색상
- 브랜드: `primary-{50~900}` (green 계열, 600이 기본)
- 카드: `bg-white rounded-xl shadow-sm p-6`
- 페이지 배경: `bg-gray-50`
- 버튼: `bg-primary-600 hover:bg-primary-700 text-white`
- 보조 텍스트: `text-gray-500 text-sm`

### StatusBadge 상태값
```
상품: NORMAL | LOW_STOCK | OUT_OF_STOCK | SCHEDULED
주문: QUOTE_REQUESTED | NEGOTIATING | CONFIRMED | PREPARING | SHIPPING | COMPLETED | CANCELLED
거래처: ACTIVE | INACTIVE | PENDING
```

---

## 페이지 구현 체크리스트

### 판매자
- [ ] dashboard — SummaryCard 4개, 최근 주문 테이블, 이번 주 출하 일정
- [ ] calendar — 월간 달력, 이벤트 타입별 색상, 날짜 클릭 상세 패널
- [ ] partners — 거래처 테이블, 검색/필터, 행 클릭 슬라이드 패널
- [ ] products — 상품 목록, 상태 필터, 등록 모달 (React Hook Form)
- [ ] orders — 탭(견적/진행/완료), 상세 패널, 상태 변경 버튼
- [ ] chat — 채팅방 목록 (좌), 메시지 창 (우), Realtime 구독

### 구매자
- [ ] dashboard — SummaryCard 4개, 진행 주문 현황, 납품 예정
- [ ] calendar — 판매자와 동일 패턴
- [ ] partners — 판매자와 동일 패턴
- [ ] browse — 상품 카드 그리드, 카테고리/가격 필터, 견적 요청 버튼
- [ ] orders — 구매자 관점 주문 목록, 상태 추적
- [ ] chat — 판매자와 동일 패턴

### 공통
- [x] AppLayout (Sidebar + TopBar + main + AIChatPanel)
- [x] AIChatPanel (우측 고정 AI 패널)
- [x] TopBar (프로필 드롭다운)
- [x] profile/page.tsx (마이페이지)

---

## 실전 발견 사항

> **agent 전용 기록 공간**: 실제 작업을 통해 검증된 패턴과 함정만 기록한다.
> 가설이나 일반적인 Next.js 지식은 추가하지 않는다.

### 검증된 패턴

#### Vercel 배포 설정 (모노레포 구조)

모노레포 루트(`web/`)와 앱 디렉토리(`web/frontend/`) 양쪽에 `vercel.json`이 필요하다.

```
web/
├── vercel.json          ← { "framework": "nextjs", "rootDirectory": "frontend" }
└── frontend/
    └── vercel.json      ← { "framework": "nextjs", "buildCommand": "npm run build", ... }
```

- 루트 `vercel.json`은 Vercel이 `frontend/`를 Next.js 루트로 인식하게 한다.
- `frontend/vercel.json`은 빌드/개발/설치 명령을 명시한다.
- `output: 'standalone'`은 Vercel 배포에서 불필요 (Docker 전용). 추가하지 않는다.
- App Router는 새로고침 시 404 처리를 자체 제공하므로 `vercel.json`에 rewrites 불필요.

#### API URL 환경변수 처리 (검증됨)

`lib/api.ts`에서 BASE_URL을 아래 패턴으로 선언한다. 환경변수 미설정 시 로컬 기본값으로 폴백.

```typescript
const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
```

Vercel 배포 후 Railway URL로 전환할 때는 `NEXT_PUBLIC_API_URL` 환경변수만 변경하면 되며, 코드 수정이 불필요하다.

### 주의사항 & 함정

- `AIChatPanel`이 `w-1/2`를 차지하므로, 페이지 콘텐츠(`main`)는 `min-w-0`이 필수. 없으면 flex 오버플로우 발생.
- 사이드바 메뉴에 `AI 업무 도우미` 항목을 추가하지 말 것. AI는 `AIChatPanel`로만 접근.
- `/ai-assistant` 라우트는 사용하지 않음 (파일은 남아있으나 사이드바 미노출).
- `/profile` 페이지는 `isFullPage = true` → Sidebar, AIChatPanel 숨김. TopBar만 유지. 전체 화면을 마이페이지가 차지.

### Supabase SSR 쿠키 타입 패턴 (검증됨)

`@supabase/ssr` 0.5.2부터 `CookieOptionsWithName`에 `value` 필드가 없어 컴파일 오류 발생.
`lib/supabase/server.ts`와 `middleware.ts` 양쪽 모두 아래 패턴을 사용한다.

```typescript
// lib/supabase/server.ts, middleware.ts 공통 패턴
import { createServerClient } from '@supabase/ssr';
import type { CookieOptions } from '@supabase/ssr';

// CookieOptionsWithName 사용 금지 — 0.5.2에서 value 필드 없음
// setAll 콜백 파라미터는 인라인 타입으로 명시
setAll(cookiesToSet: { name: string; value: string; options: CookieOptions }[]) {
  cookiesToSet.forEach(({ name, value, options }) => ...);
}
```

#### useMutation 온디맨드 호출 패턴 (검증됨)

자동 fetch가 아닌 버튼 클릭 시에만 호출하는 AI/에이전트 훅은 `useQuery` 대신 `useMutation`을 사용한다.
`isIdle` → `isPending` → `data` / `isError` 순서로 상태를 분기 렌더링한다.

```typescript
// hooks/useScheduleAgent.ts
export function useScheduleRecommend() {
  return useMutation({
    mutationFn: async (params: { year: number; month: number }) => {
      const res = await api.post<SuccessResponse<ScheduleRecommendResponse>>(
        '/schedule-agent/recommend',
        params
      );
      return res;
    },
  });
}

// 컴포넌트에서 사용
const { mutate, data, isPending, isError, isIdle } = useScheduleRecommend();
const result = data?.data;  // SuccessResponse 래퍼 안의 data 필드

// 상태 분기: isIdle → 초기 안내 + 버튼 / isPending → 스피너 / result → 결과 / isError → 에러
```

#### 캘린더 사이드바에 AI 패널 추가 시 래퍼 패턴 (검증됨)

캘린더 페이지의 사이드 컬럼(기존 단일 카드)에 AI 패널을 추가할 때는 `space-y-6` 래퍼 div로 묶는다.
`lg:grid-cols-4` 레이아웃에서 컬럼 수 변경 없이 수직 스택으로 패널을 추가할 수 있다.

```tsx
<div className="space-y-6">          {/* 새 래퍼 — 기존 col 설정 제거 */}
  <div className="rounded-xl bg-white p-6 shadow-sm">  {/* 기존 날짜 상세 카드 */}
    ...
  </div>
  <ScheduleAgentPanel year={year} month={month} />
</div>
```

#### AI 패널 컴포넌트 디렉토리 위치

`components/calendar/` 디렉토리는 기본 생성 안 됨 — `mkdir -p`로 먼저 생성 후 파일 작성.

### 도메인 타입 → `Record` 키 타입 패턴 (검증됨)

상태 전이 맵처럼 값이 도메인 타입인 경우 `Record<string, DomainType>` 형태로 선언한다. 키는 런타임에 동적으로 조회되므로 `string`으로 유지한다.

```typescript
// seller/orders/page.tsx
import type { Order, OrderStatus } from '@/types';

const nextStatusMap: Record<string, OrderStatus> = {
  QUOTE_REQUESTED: 'NEGOTIATING',
  NEGOTIATING: 'CONFIRMED',
  // ...
};
// → nextStatusMap[order.status] 의 반환 타입이 OrderStatus로 좁혀짐
```
