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
│   ├── common/
│   │   ├── PageHeader.tsx
│   │   ├── StatusBadge.tsx
│   │   ├── SummaryCard.tsx
│   │   ├── DataTable.tsx
│   │   ├── SearchFilterBar.tsx
│   │   ├── EmptyState.tsx
│   │   └── Modal.tsx
│   └── dashboard/
│       └── TodayTasksWidget.tsx     ← role='seller'|'buyer' — 오늘 할 일 요약
├── hooks/
│   ├── useAuth.ts                  ← user, signOut (signOut에서 AI 대화 캐시도 초기화)
│   ├── useAIStream.ts              ← AI 채팅 호출 + aiChatStore 에 turn 저장
│   ├── useAIHistory.ts             ← /ai/history fetch + aiChatStore hydrate
│   └── useChat.ts
├── store/
│   ├── authStore.ts                ← user, setSession, logout (탭별 격리 persist)
│   ├── aiChatStore.ts              ← AI 대화 turns(최대 100), localStorage persist (글로벌)
│   └── uiStore.ts                  ← aiPanelOpen, toggleAIPanel (사이드바 state 없음 — 호버 전용)
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
├── Sidebar (좌, md 이상 인라인 / 모바일 fixed 오버레이)
└── 우측 영역 (flex-1)
    ├── TopBar (상, h-16, 모바일 햄버거 버튼 포함)
    └── 콘텐츠 영역 (flex row)
        ├── main (flex-1, min-w-0)            ← 페이지별 콘텐츠
        └── AIChatPanel (xl 이상에서만 표시)  ← xl:w-[360px] 2xl:w-[400px]
```

**반응형 레이아웃 핵심 규칙:**
- Sidebar: **2단계 반응형** (lg 미만 / lg 이상) — 호버 전용, 핀/토글 개념 완전 제거됨
  - lg 미만(<1024px): `absolute inset-y-0 left-0 z-40 shadow-sm` 오버레이. **항상 w-16 collapsed 디폴트**. 호버 시에만 w-56 슬라이드 펼침, 마우스 떠나면 즉시 w-16 축소. 화살표/토글 버튼 **없음**. 본문 자리는 자리표시 div(`block lg:hidden w-16 flex-shrink-0`)가 항상 차지 → 호버 펼침 시 본문이 밀리지 않음.
  - 큰 화면(≥1024px): `lg:relative lg:w-56` 인라인 + 항상 펼침 강제(`expanded = isLargeScreen || isHovered`).
- Sidebar 상태 모델: `isHovered`(local) + `isLargeScreen`(matchMedia) + `canHover`(matchMedia `(hover: hover)`). **Zustand 의존성 제거됨**. `expanded = isLargeScreen || isHovered`. 터치 디바이스에서 끈적한 호버 방지를 위해 `handleMouseEnter`는 `canHover` 체크 후에만 setIsHovered(true) → 터치 디바이스는 항상 collapsed.
- AppLayout: **`relative` 필수** — lg 미만에서 Sidebar가 `absolute` 이므로 부모 기준 배치. 빠뜨리면 사이드바가 화면 전체로 튐.
- AppLayout: resize 핸들러 제거됨 — Sidebar가 자체 matchMedia로 lg 분기 처리.
- AppLayout: 모바일 오버레이 배경 div 제거됨 (사이드바가 absolute overlay라 본문을 가리지 않으므로 backdrop 불필요).
- TopBar: 햄버거 버튼 제거됨 — 사이드바가 모든 화면에서 항상 보이므로 별도 토글 버튼 불필요. 좌측에는 빈 `<div />` 자리표시만 유지.
- uiStore: 사이드바 관련 state(`sidebarOpen`/`toggleSidebar`/`setSidebarOpen`) **완전 제거됨**. AI 패널 state(`aiPanelOpen`/`toggleAIPanel`/`setAIPanelOpen`)만 유지.
- AIChatPanel: 축소 상태(aiPanelOpen=false)는 모든 화면에서 w-12 바 표시 / 확장 상태(aiPanelOpen=true)는 모바일(md 미만) fixed 오버레이, md 이상 인라인 w-[360px] xl:w-[400px] 2xl:w-[440px]
- main padding: 모바일 `p-4`, 데스크탑 `md:p-6`

**실제 AppLayout.tsx (단순화 — 사이드바 state 의존성 완전 제거):**
```tsx
export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user } = useAuthStore();
  const pathname = usePathname();
  const menus = user?.role === 'SELLER' ? sellerMenus : buyerMenus;
  const isFullPage = pathname === '/profile';

  // useUIStore / resize 핸들러 없음 — Sidebar가 자체 matchMedia로 lg 분기 처리
  return (
    // relative 필수 — lg 미만에서 Sidebar가 absolute 로 부모 기준 배치됨
    <div className="relative flex h-screen overflow-hidden bg-gray-50">
      {!isFullPage && <Sidebar menus={menus} currentPath={pathname} role={user?.role} />}
      <div className="flex flex-1 flex-col overflow-hidden">
        <TopBar user={user} />
        <div className="flex flex-1 overflow-hidden">
          <main className="flex-1 overflow-y-auto p-4 md:p-6 min-w-0">{children}</main>
          {!isFullPage && <AIChatPanel />}
        </div>
      </div>
    </div>
  );
}
```

**Sidebar.tsx 핵심 패턴 (호버 전용 — 핀/토글 버튼 완전 제거, lg 강제 펼침, 터치 디바이스 호버 회피):**
```tsx
const [isHovered, setIsHovered] = useState(false);
const [isLargeScreen, setIsLargeScreen] = useState(false);
const [canHover, setCanHover] = useState(true);

useEffect(() => {
  const mq = window.matchMedia('(min-width: 1024px)');
  const update = () => setIsLargeScreen(mq.matches);
  update();
  mq.addEventListener('change', update);
  return () => mq.removeEventListener('change', update);
}, []);

useEffect(() => {
  const mq = window.matchMedia('(hover: hover)');     // 터치 디바이스(hover: none)는 끈적한 호버 회피
  const update = () => setCanHover(mq.matches);
  update();
  mq.addEventListener('change', update);
  return () => mq.removeEventListener('change', update);
}, []);

// 큰 화면: 항상 펼침 / 그 외: 호버 여부만으로 결정 (Zustand 핀 의존성 제거됨)
const expanded = isLargeScreen || isHovered;

const handleMouseEnter = () => { if (canHover) setIsHovered(true); };

return (
  <>
    {/* lg 미만 자리표시 — 사이드바가 absolute 로 떠있어도 본문 시작점 고정 */}
    <div className="block lg:hidden w-16 flex-shrink-0" aria-hidden="true" />
    <aside
      onMouseEnter={handleMouseEnter}
      onMouseLeave={() => setIsHovered(false)}
      className={cn(
        'flex flex-col border-r border-gray-200 bg-white transition-all duration-200',
        'absolute inset-y-0 left-0 z-40 shadow-sm',              // lg 미만: absolute hover overlay
        expanded ? 'w-56' : 'w-16',
        'lg:relative lg:w-56 lg:shadow-none lg:z-auto'            // lg: 인라인 강제 펼침
      )}
    >
      {/* 로고 / 역할 배지 / 메뉴 — 토글 버튼 없음 */}
    </aside>
  </>
);
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
//
// 종(Bell) 알림: 별도 컴포넌트 NotificationBell 로 분리되어 있음.
// TopBar 는 <NotificationBell /> 만 렌더하고 끝 — 상태/구독 로직 직접 보유 X.
```

---

## 알림(Notification) 시스템 (실제 기준)

```
backend                                 frontend
─────────                               ────────
order_service / chat_service            useNotificationRealtime  ← 단일 mount (NotificationBell 내부)
   ↓ INSERT public.notifications          ↓ supabase.channel(`notifications:${userId}`)
   ↓ Supabase Realtime publication        ↓ filter: user_id=eq.${userId}
   ↓ INSERT/UPDATE 모두 본인 행만 푸시 ─► queryClient.invalidateQueries(['notifications'])
                                          ↓
GET  /notifications?limit=30            useNotifications({ limit, onlyUnread })
GET  /notifications/unread-count        useUnreadCount()  ← refetchInterval 60s (Realtime 끊김 대비)
POST /notifications/{id}/read           useMarkNotificationRead()  ← Optimistic (race-safe)
POST /notifications/read-all            useMarkAllNotificationsRead()  ← Optimistic (race-safe)
```

**주요 규칙:**
- Realtime 구독은 **NotificationBell 한 곳** 에서만 호출 (AppLayout/TopBar 에서 중복 호출 금지 — 채널 누수)
- Realtime 은 INSERT + UPDATE 둘 다 listen — 다른 탭에서 mark_read 하면 이 탭에도 즉시 반영
- 카운트 뱃지는 `useUnreadCount()` 우선, fallback 으로 `listQuery.data.meta.unread_count` 사용
- 두 쿼리 모두 `['notifications', ...]` prefix 키 → Realtime 시 한 번의 invalidate 로 동기화됨
- 백엔드 응답 형태: `SuccessResponse<Notification[]>` + `meta: { unread_count, total }` (페이지네이션 meta 와 같은 자리)
- 행 클릭 → **`await markRead.mutateAsync(id)` 후** `router.push(link_url)`. `mutate()` fire-and-forget 으로 호출 직후 navigate 하면 fetch 가 abort 됨 — 항상 await. order 관련은 `/{role}/orders?id=...`, NEW_MESSAGE 는 `/{role}/chat?room_id=...`. orders/chat 페이지는 `?id=` / `?room_id=` 쿼리로 자동 모달/방 선택 처리 (각 page.tsx 의 `useEffect(() => searchParams.get(...))` 참조).

### Optimistic mark-read mutation 의 race 회피 정책 (검증됨)

증상: "안 읽음 표시가 안 사라진다." 백엔드 access log 에 POST 자체가 안 찍힘.

원인 3가지를 모두 차단해야 함:
1. **router.push 가 fetch abort** — `markRead.mutate(id)` 직후 `router.push(...)` 호출하면 React Query 의 onMutate microtask 가 진행 중인 동안 navigation 시작 → fetch 가 abort 또는 무시. 해결: `await markRead.mutateAsync(id)` 로 끝까지 기다린 뒤 navigate.
2. **cancelQueries hang** — `useUnreadCount` 의 60초 polling 이 in-flight 일 때 onMutate 안의 `await queryClient.cancelQueries(['notifications'])` 가 정상 종료 안 되면 mutationFn 실행 안 됨. 해결: **onMutate 에서 cancelQueries 호출 안 함**. 어차피 setQueryData 로 즉시 덮으므로 cancel 불필요.
3. **invalidate 후 refetch 가 옛 응답 덮어씀** — onSettled 에서 `invalidateQueries` 호출하면 polling refetch 가 즉시 실행되며, 그 응답이 optimistic 으로 만든 0 카운트를 옛 N 카운트로 덮을 수 있음. 해결: **onSettled invalidate 제거**. 대신 onSuccess 에서 server 응답으로 `setQueriesData` 직접 업데이트, 그리고 다른 탭/디바이스 동기화는 **Realtime UPDATE 이벤트** 로 보완.

추가 안전장치: `useUnreadCount` 에 `refetchOnMount: false` — mutation 직후 mount 변화로 인한 refetch race 방지.

`setQueriesData` 의 콜백 안에서는 `unread-count` 단일 객체 캐시 (`data` 가 배열 아님) 와 list 캐시를 구분해야 함. `if (!Array.isArray(cast.data)) return old;` 로 list 만 처리.

회귀 영향: invalidate 제거로 기존에 의존하던 자동 refetch 가 사라지지만, (a) 같은 탭에서는 onSuccess 의 setQueriesData 가 server truth 를 직접 cache 에 박고, (b) 다른 탭/디바이스는 Realtime UPDATE 이벤트가 invalidate 트리거. 60초 polling fallback 도 유지.

**상대 시간 헬퍼**: `lib/date.ts` 의 `formatRelativeKst(iso)` 사용. "방금" / "{N}분 전" / "{N}시간 전" / "YYYY-MM-DD"(KST) 4단계.

---

## AIChatPanel (실제 기준)

```typescript
// frontend/components/layout/AIChatPanel.tsx
// - useAuthStore로 role 감지 → sellerQuickPrompts / buyerQuickPrompts 자동 선택
// - useAIStream 훅 사용 → { isStreaming, manualReview, stream } 만 destructure
//   (response 는 더 이상 직접 안 씀 — store 의 turns 가 SSOT)
// - useAIHistory(100) 호출로 store hydrate 트리거
// - useAIChatStore 의 turns 를 구독해 사용자/AI 말풍선 형태로 모두 표시
// - 새 응답이 와도 이전 대화가 유지되며, 페이지 이동/새로고침 후에도 localStorage 에서 복원
// - 입력: Enter(전송), Shift+Enter(줄바꿈) 지원
// - 별도 라우트(/ai-assistant) 없음
//
// 반응형 동작 (단일 컴포넌트, 조건부 return 방식):
// - 축소(aiPanelOpen=false): 모든 화면에서 w-12 바 표시. hidden 없음 — 항상 보임
// - 확장(aiPanelOpen=true):
//   - 모바일(md 미만): fixed inset-y-0 right-0 z-50 w-[320px] + 배경 오버레이(z-40)
//   - md 이상: 인라인 flex w-[360px] xl:w-[400px] 2xl:w-[440px]
// - xl 이상에서 resize 시 setAIPanelOpen(true) 자동 호출 (useEffect)
// - isMobile 상태는 컴포넌트 내부에서 window.innerWidth < 768 로 감지
//
// uiStore에 aiPanelOpen / toggleAIPanel / setAIPanelOpen 사용
// 채팅 UI는 chatUI 변수로 한 번만 작성 후 확장 상태 두 곳에서 재사용
```

### AIChatPanel turns 렌더 패턴 (검증됨, 2026-04-30)

좁은 패널(폭 320~440px)에 맞춘 **컴팩트 사이즈**로 turns 모두 표시.
ai-assistant 페이지의 풀 사이즈 (text-sm, max-w-[75%], px-4 py-2) 와 다른 컴팩트 톤을 사용한다:
- 텍스트: `text-xs` (페이지는 `text-sm`)
- 말풍선: `max-w-[85%] rounded-2xl px-3 py-1.5` (페이지는 `max-w-[75%] rounded-2xl px-4 py-2`)
- 컨테이너 padding: `p-3 space-y-1.5`
- 날짜 구분선 폰트: `text-[10px]`
- manual review 배너 폰트: `text-[11px]` + 아이콘 `h-3.5 w-3.5`

```tsx
const { isStreaming, manualReview, stream } = useAIStream();  // response 는 안 씀
useAIHistory(100);
const turns = useAIChatStore((s) => s.turns);
const messagesEndRef = useRef<HTMLDivElement>(null);
const lastTurn = turns.length > 0 ? turns[turns.length - 1] : null;
const showManualReviewBanner = manualReview && !!lastTurn && !lastTurn.pending;

useEffect(() => {
  messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
}, [turns.length, lastTurn?.response]);

// pending 마지막 turn 의 AI 말풍선은 깜빡이는 캐럿만 표시
const isLastPending = idx === turns.length - 1 && turn.pending && turn.response === '';
```

**핵심**: `response` state 는 useAIStream 이 외부 호환성으로 유지하되,
실제 화면 렌더는 `useAIChatStore.turns` 가 SSOT (Single Source of Truth).
이렇게 해야 새 응답이 와도 이전 대화가 사라지지 않고, 페이지 이동 후 돌아와도 그대로 남는다.

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
const { aiPanelOpen, toggleAIPanel } = useUIStore();  // 사이드바 state는 없음 (Sidebar 자체 호버 처리)
```

### Tailwind 색상
- 브랜드: `primary-{50~900}` (green 계열, 600이 기본)
- 카드: `bg-white rounded-xl shadow-sm p-6`
- 페이지 배경: `bg-gray-50`
- 버튼: `bg-primary-600 hover:bg-primary-700 text-white`
- 보조 텍스트: `text-gray-500 text-sm`

### Tailwind content 스캔 경로 (필수)
`tailwind.config.ts`의 `content` 배열에는 **className 문자열이 등장하는 모든 디렉토리**를 포함해야 한다. JIT 모드는 스캔 경로 밖에 string literal로 존재하는 클래스를 인식하지 못해 빌드 CSS에서 누락시킨다.

```ts
content: [
  './app/**/*.{js,ts,jsx,tsx,mdx}',
  './components/**/*.{js,ts,jsx,tsx,mdx}',
  './constants/**/*.{js,ts,jsx,tsx,mdx}',  // ORDER_STATUS_CONFIG.solidClassName, EVENT_TYPE_COLOR_CLASS 등
  './hooks/**/*.{js,ts,jsx,tsx,mdx}',
  './lib/**/*.{js,ts,jsx,tsx,mdx}',
],
```

특히 `constants/status.ts` 의 `ORDER_STATUS_CONFIG[*].solidClassName` (`bg-purple-500`, `bg-orange-500`, `bg-indigo-500`, `bg-blue-500`, `bg-green-500`, `bg-red-500`, `bg-gray-500`) 와 `EVENT_TYPE_COLOR_CLASS` 가 오직 `constants/` 안에서만 string literal로 정의된다. `constants/` 가 content에 없으면 캘린더 셀의 일정 색이 모두 누락되어 흰 배경에 흰 글씨로 보이는 버그가 재발한다.

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
- [x] partners — 거래처 테이블 (서버 사이드 필터), 즐겨찾기 토글, AddPartnerModal, 빠른 액션(채팅 / 정기배송 신청 — ACTIVE 만) — 주문 작성은 V1 숨김 (전용 새 페이지 미존재)
- [x] members — 회원 검색 카드, 프로필 모달, 채팅 생성, 거래처 추가 버튼
- [ ] products — 상품 목록, 상태 필터, 등록 모달 (React Hook Form)
- [x] orders — 탭(견적/진행/완료), 상세 패널, 상태 변경 + 협상가 제시/수락/거절 + 취소
- [ ] chat — 채팅방 목록 (좌), 메시지 창 (우), Realtime 구독

### 구매자
- [ ] dashboard — SummaryCard 4개, 진행 주문 현황, 납품 예정
- [ ] calendar — 판매자와 동일 패턴
- [x] partners — 판매자와 동일 패턴 + 빠른 액션 "주문 작성" → /buyer/browse?seller_id=... + 정기배송 신청(ACTIVE 만)
- [x] members — 판매자와 동일 패턴 (채팅 이동: /buyer/chat) + 거래처 추가 버튼
- [x] browse — 상품 카드 그리드, 카테고리/가격 필터, 견적 요청 버튼, ?seller_id= 쿼리로 판매자 필터
- [x] orders — 견적 생성/수정/취소 모달 + 협상가 제시/수락/거절 + 상세 슬라이드
- [x] inventory — 자동 누적 재고 목록(테이블), 수량/메모 수정 모달, soft-delete 모달, 검색 디바운스 + 정렬(recent/quantity/name) + 페이지네이션
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

- **Sidebar lg 미만 absolute 배치 시 부모 `relative` 필수.** AppLayout 루트 div에 `relative` 빠뜨리면 사이드바가 화면 전체 기준으로 튐. 또한 본문이 좌측으로 붙어 가려지지 않도록 `<div className="block lg:hidden w-16 flex-shrink-0" />` 자리표시 div가 사이드바 앞에 항상 있어야 한다.
- **Sidebar는 호버 전용 — 핀/토글 state 없음.** `expanded = isLargeScreen || isHovered` 단순 OR 조합. 과거에는 `sidebarOpen`(zustand 핀) + `isHovered`(local) 합산이었으나, "lg 미만으로 줄였을 때 사이드바가 펼쳐진 채로 시작되어 다시 화살표를 눌러야 collapsed 됨" 문제로 인해 핀 개념과 화살표 토글 버튼을 모두 제거. 이제 lg 미만에서는 무조건 collapsed로 시작하고 마우스 호버 시에만 펼쳐진다.
- **`window.matchMedia('(min-width: 1024px)')`로 isLargeScreen 동기화.** Tailwind `lg:` 만으로는 JS 분기가 안 되므로 `useState + matchMedia.addEventListener('change')` 패턴 사용. resize 이벤트보다 효율적. AppLayout에서 따로 resize 핸들러를 둘 필요 없음 — Sidebar가 자체 처리.
- **터치 디바이스 호버 회피: `(hover: hover)` matchMedia 사용.** 모바일/태블릿에서 onMouseEnter는 탭 시 발화하고 다음 탭까지 호버 상태가 유지되는 "끈적한 호버" 문제가 있다. `canHover` 상태로 호버 가능한 디바이스에서만 setIsHovered(true)를 호출하여 이를 회피. 토글 버튼이 없으므로 터치 디바이스에서는 lg 미만일 때 항상 collapsed 상태로 고정 (디자인 의도).
- **TopBar 햄버거 버튼 없음.** 사이드바가 모든 화면에서 항상 보이는 collapsed 패턴이라 별도 토글 버튼이 불필요. 좌측에 빈 `<div />` 만 placeholder로 둔다. `useUIStore`/`Menu` 아이콘 임포트도 제거.
- `AIChatPanel`이 xl 이상에서 `w-[400px]`를 차지하므로, 페이지 콘텐츠(`main`)는 `min-w-0`이 필수. 없으면 flex 오버플로우 발생.
- AIChatPanel은 `isMobile` state + `aiPanelOpen` 상태를 조합해 조건부 return으로 렌더링한다. Tailwind `hidden` 클래스 분기 방식이 아닌 JS 조건 분기 방식을 사용한다. 축소 상태는 항상 w-12 바를 반환, 모바일 확장은 fixed 오버레이, md 이상 확장은 인라인 div를 반환한다.
- 사이드바 메뉴에 `AI 업무 도우미` 항목을 추가하지 말 것. AI는 `AIChatPanel`로만 접근.
- `/ai-assistant` 라우트는 사용하지 않음 (파일은 남아있으나 사이드바 미노출).
- `/profile` 페이지는 `isFullPage = true` → Sidebar, AIChatPanel 숨김. TopBar만 유지. 전체 화면을 마이페이지가 차지.

### Supabase 클라이언트 — 탭별 격리 storage (검증됨, 2026-04-27 재설계)

`@supabase/ssr` 의 `createBrowserClient` (쿠키 기반)는 더 이상 사용하지 않는다. 같은 도메인 내 탭이 서로 다른 계정으로 동시 로그인 가능하도록 `@supabase/supabase-js` 의 `createClient` + 탭별 `storageKey` 패턴으로 전환되었다. 자세한 내용은 `SKILL_AUTH.md` 참조.

핵심 한 줄 요약:
- `lib/supabase/client.ts` — `storageKey: 'agriflow-auth-{tabId}'`, `storage: window.localStorage`, 모듈 레벨 `_client` 캐시
- `lib/supabase/server.ts` — deprecated, 호출 시 throw
- `middleware.ts` — `matcher: []` 비활성화, 인증 가드는 `<AuthGuard>` (클라이언트)에서
- `store/authStore.ts` — persist name도 tabId suffix, `loginExpiresAt` 필드로 2일 만료 정책

#### 캘린더 일정 클릭 → EventDetailModal 패턴 (검증됨, 2026-04-27)

캘린더 셀의 일정 항목과 우측 "전체 일정" 리스트의 일정 카드 클릭 시 동일하게 상세 모달이 열려야 한다.
페이지에서는 `selectedEvent: CalendarEvent | null` 상태 하나만 두고, 셀/리스트 양쪽 모두 `setSelectedEvent(ev)` 호출.

**셀 안의 일정 클릭은 반드시 `e.stopPropagation()`** — 셀 자체 클릭은 `setSelectedDate(dateStr)` + `setDayModalDate(dateStr)` 이므로 이벤트 버블링이 일어나면 두 모달이 동시에 열려 충돌한다. 또한 셀 안의 일정 노드를 `<div>` 가 아닌 `<button type="button">` 으로 만들어 키보드 접근성도 확보.

```tsx
{dayEvents.slice(0, 3).map((ev) => (
  <button
    key={ev.id}
    type="button"
    onClick={(e) => { e.stopPropagation(); setSelectedEvent(ev); }}
    className={cn('block w-full rounded px-1 py-0.5 text-left text-[10px] text-white hover:opacity-90', getCalendarEventColorClass(ev))}
  >
    <div className="truncate font-medium">{main}</div>
    {sub && <div className="truncate text-[9px] text-white/80">{sub}</div>}
  </button>
))}
{dayEvents.length > 3 && (
  <p className="mt-0.5 rounded bg-gray-200 px-1 py-0.5 text-center text-[10px] font-semibold text-gray-700">
    +{dayEvents.length - 3}개 더보기
  </p>
)}
```

**우측 리스트 클릭은 모달 오픈만, 날짜 이동(setSelectedDate) 없음.** 이전에는 `setSelectedDate(ev.event_date)`로 날짜 이동만 했으나, "정보가 안 보인다"는 사용자 페인포인트의 핵심이라 모달 직접 오픈으로 변경. 리스트 카드의 활성 표시도 `selectedDate === ev.event_date` 가 아닌 `selectedEvent?.id === ev.id` 로 변경.

**(2026-04-27 갱신) 우측 리스트 클릭은 캘린더 그리드 월 이동 + 모달 오픈을 함께 수행한다.** 리스트가 모든 월의 일정을 보여주므로(아래 "전체 월 일정" 패턴 참조) 다른 월 일정을 클릭하면 그리드도 함께 그 월로 이동해야 위치를 인식할 수 있다.

```ts
const handleListItemClick = (ev: CalendarEvent) => {
  const [y, m] = ev.event_date.split('-').map(Number);
  if (y && m) { setYear(y); setMonth(m); }
  setSelectedDate(ev.event_date);
  setSelectedEvent(ev);   // EventDetailModal 직접 오픈 — 사용자가 그 카드를 직접 눌렀으므로
};

const handleListHeaderClick = (date: string) => {
  const [y, m] = date.split('-').map(Number);
  if (y && m) { setYear(y); setMonth(m); }
  setSelectedDate(date);
  setDayModalDate(date);  // 날짜 그룹 헤더는 그날 전체를 보여주는 DayEventsModal 오픈
};
```

**셀 안 일정은 클릭 핸들러 없는 div** — `<button onClick={(e) => { e.stopPropagation(); setSelectedEvent(ev); }}>` 패턴은 폐기되었다. 이전에는 셀 안 일정 클릭은 EventDetailModal 직접 오픈, 셀 빈 영역 클릭은 DayEventsModal 오픈으로 두 진입점이 갈렸다. 사용자 일관성 요구로 **어디든 클릭하면 무조건 DayEventsModal**만 뜨도록 통일.

```tsx
{dayEvents.slice(0, 3).map((ev) => {
  const { main, sub } = getEventLabels(ev);
  return (
    <div
      key={ev.id}
      className={cn(
        'block w-full rounded px-1 py-0.5 text-left text-[10px] text-white',
        getCalendarEventColorClass(ev)
      )}
    >
      <div className="truncate font-medium">{main}</div>
      {sub && <div className="truncate text-[9px] text-white/80">{sub}</div>}
    </div>
  );
})}
```

`hover:opacity-90` 도 함께 제거 — 셀 hover 효과(`hover:bg-gray-50`)에 자연스럽게 통합되도록. EventDetailModal 진입점은 이제 두 곳: ① DayEventsModal 안의 카드 클릭 (`onSelectEvent`), ② 우측 리스트의 카드 클릭 (`handleListItemClick`).

**EventDetailModal** (`components/calendar/EventDetailModal.tsx`):
- Props: `event: CalendarEvent | null`, `onClose: () => void`, `role: 'seller' | 'buyer'`
- 헤더: 메인=`product_name ?? title`, 서브=`order_number`(있을 때만)
- 본문: 색상 점 + 유형 뱃지(EVENT_TYPE_OPTIONS 라벨), 날짜(YYYY년 M월 D일 한국식), 시간(HH:MM ~ HH:MM 또는 "종일"), 설명(있을 때만)
- `order_id` 있으면 "주문 상세 보기" 버튼 → role 따라 `/buyer/orders/{id}` 또는 `/seller/orders/{id}`
- 푸터: 닫기 버튼 + 삭제 버튼(`useDeleteCalendarEvent` 훅, `confirm()` 후 `mutateAsync` → `onClose()`)
- `event === null` 일 때는 `Modal isOpen={false}` 로 빈 모달 반환 (조건부 렌더링 없이도 안전하게 hooks 호출)

```tsx
<EventDetailModal event={selectedEvent} onClose={() => setSelectedEvent(null)} role="seller" />
```

#### 캘린더 셀 클릭 → DayEventsModal 패턴 (검증됨, 2026-04-27)

날짜 셀(빈 영역) 클릭 시 단순 `setSelectedDate`만으로는 시각적 피드백이 약하다. 클릭 시 그날의 전체 일정을 리스트로 보여주는 별도 모달(`DayEventsModal`)을 띄운다.

**페이지 상태 구조 — 3단계 상태 분리**:
```typescript
const [selectedDate, setSelectedDate] = useState<string | null>(null);   // 셀 하이라이트용
const [dayModalDate, setDayModalDate] = useState<string | null>(null);   // 날짜 모달 트리거
const [selectedEvent, setSelectedEvent] = useState<CalendarEvent | null>(null); // EventDetailModal 트리거
```

**셀 onClick 흐름** — 두 상태를 함께 세팅:
```tsx
onClick={() => {
  setSelectedDate(dateStr);     // 시각 피드백 (border-primary-500 bg-primary-50)
  setDayModalDate(dateStr);     // 모달 오픈
}}
```

셀 안의 일정 버튼은 기존 패턴 유지 — `e.stopPropagation()` 후 `setSelectedEvent(ev)`로 EventDetailModal 직접 오픈 (Day 모달을 거치지 않는 단축 흐름).

**DayEventsModal 협업 — 두 진입점 처리**:
```tsx
<DayEventsModal
  date={dayModalDate}
  events={dayModalDate ? visibleEvents.filter((e) => e.event_date === dayModalDate) : []}
  onClose={() => setDayModalDate(null)}
  onSelectEvent={(ev) => {
    setDayModalDate(null);   // 일정 카드 클릭 → Day 모달 닫고 Detail 모달 오픈
    setSelectedEvent(ev);
  }}
  onAddEvent={(d) => {
    setDayModalDate(null);   // "일정 추가" 버튼 → Day 모달 닫고 추가 모달 오픈
    setSelectedDate(d);
    setShowModal(true);
  }}
  role="seller"  // 또는 "buyer"
/>
```

**컴포넌트 위치**: `components/calendar/DayEventsModal.tsx`. 헤더는 한국식 + 요일(`2026년 5월 6일 (수)`), 본문은 start_time 오름차순 정렬(없으면 마지막), 일정 없으면 "이 날짜에 등록된 일정이 없습니다" 메시지, 푸터는 "일정 추가" + "닫기" 버튼. 기존 공통 `Modal` 컴포넌트 재사용.

#### 캘린더 페이지 — 12-grid 레이아웃 + 셀 균일 높이 (검증됨, 2026-04-29)

기존 `lg:grid-cols-4 + col-span-3 / 1` 비율(75:25)에서, **12-grid 기반 단계 분할**로 리디자인되었다.
`lg` 에서는 67:33, `xl` 이상 큰 화면에서는 75:25 — 좁은 lg 화면에서도 사이드바가 잘 읽히고 xl 에서는 달력에 더 많이 할당.

레이아웃 (seller/buyer 동일):
- 부모: `grid grid-cols-1 gap-6 lg:grid-cols-12`
- 달력 wrapper: `lg:col-span-8 xl:col-span-9 rounded-xl bg-white p-6 shadow-sm`
- 사이드바 wrapper: `lg:col-span-4 xl:col-span-3 space-y-4`

날짜 셀 균일 높이 패턴:
- 빈 셀(이전 달): `<div className="h-28 rounded-lg bg-gray-50/40" />` — 톤 다운된 배경
- 일반 셀: `h-28 cursor-pointer overflow-hidden rounded-lg border p-2 transition-colors`
  - 기본 테두리 `border-gray-100`, hover `hover:border-gray-200 hover:bg-gray-50`
  - 선택됨 `border-primary-500 bg-primary-50 ring-1 ring-primary-500`
  - `h-28`(112px) **고정** + `overflow-hidden` — 일정 개수와 무관하게 모든 셀 동일 높이
- 셀 안 일정 칩: 최대 **2개** 표시, 메인 라인만(`text-[11px]`), sub 라인은 셀에서 노출 안 함
- "+N개 더보기": `bg-gray-100 text-gray-600 font-medium text-[11px]`

월 네비게이션:
- "오늘" 버튼: 좌측 화살표 옆에 작은 텍스트 버튼 — `text-xs font-medium text-gray-600 hover:bg-gray-100 hover:text-primary-700 px-2 py-1 rounded`
- 클릭 시 `setYear(today.getFullYear()); setMonth(today.getMonth() + 1)`

우측 "전체 일정" 카드:
- 스크롤 영역: `max-h-[calc(100vh-220px)] space-y-4 overflow-y-auto pr-1`
- 날짜 그룹 헤더: `sticky top-0 ... border-b-2 border-gray-200 bg-white py-2.5` — 시각 구분 강화
- 일정 카드 sub 텍스트: `truncate` 대신 `line-clamp-1` 로 가독성 확보
- 타입 라벨 뱃지: `text-xs` (이전 `text-[10px]` 대비 약간 큼)

#### 캘린더 — CANCELLED 일정 방어적 프론트 필터링 (검증됨, 2026-04-27)

백엔드 `order_service`가 CANCELLED 주문의 calendar_events를 즉시 soft-delete 하지만, 캐시·sync 누락 등 사이드 케이스에서 `order_status === 'CANCELLED'` 이벤트가 응답에 섞여 들어올 수 있다. 페이지에서 한 번 가공해 모든 노출 지점에서 같이 차단한다.

```typescript
const visibleEvents = useMemo(
  () => events.filter((e) => e.order_status !== 'CANCELLED'),
  [events]
);
```

`getEventsForDay`, `sortedEvents`, `DayEventsModal`로 전달하는 events 모두 `visibleEvents` 사용 — 셀·우측 리스트·날짜 모달 어디서도 보이지 않게 통일. seller/buyer 양쪽 동일 적용.

#### 캘린더 — dateStr 생성 방식 (timezone-safe 순수 문자열) (검증됨, 2026-04-27)

캘린더 셀의 dateStr 과 `event.event_date` 비교는 `===` 단순 문자열 비교다. `new Date(...).toISOString().split('T')[0]` 같은 방식은 KST(UTC+9)에서 자정 무렵 하루 어긋남이 발생하므로 **금지**. 항상 순수 문자열 조합으로 생성하여 timezone 영향을 차단한다.

```typescript
const buildDateStr = (d: number) =>
  `${year}-${String(month).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
```

백엔드 `event_date`는 Postgres `date` → `'YYYY-MM-DD'` 문자열로 안정적으로 직렬화되므로 양쪽이 정확히 일치한다.

#### CalendarEvent — product_name/order_status + 거래처 4필드 (검증됨, 2026-04-29 갱신)

백엔드 `CalendarEventResponse`에 `order_number`, `product_name`, `order_status` + 거래처 4필드(`buyer_name/buyer_company/seller_name/seller_company`)가 추가됨.
`order_id` 없는 일정(MEETING 등)은 모두 null. **거래처 4필드는 optional** — 백엔드 미배포 환경에서도 안전하게 동작.

```typescript
// types/calendar.ts
import type { OrderStatus } from './order';

export interface CalendarEvent {
  // 기존 필드들...
  order_number: string | null;
  product_name: string | null;
  order_status: OrderStatus | null;
  buyer_name?: string | null;
  buyer_company?: string | null;
  seller_name?: string | null;
  seller_company?: string | null;
}
```

표시 정책 (2026-04-29 변경) — **메인 = product_name fallback title, 서브 = 거래처명, 주문번호는 미노출 또는 작은 회색 텍스트로 격하**:
```tsx
// seller/calendar/page.tsx — 판매자에게 거래처는 buyer
const getEventLabels = (ev: CalendarEvent) => {
  const main = ev.product_name ?? ev.title;
  const partner = ev.buyer_company ?? ev.buyer_name ?? null;
  const sub = partner;  // 주문번호 대신 거래처명
  return { main, sub };
};

// buyer/calendar/page.tsx — 구매자에게 거래처는 seller
const getEventLabels = (ev: CalendarEvent) => {
  const main = ev.product_name ?? ev.title;
  const partner = ev.seller_company ?? ev.seller_name ?? null;
  const sub = partner;
  return { main, sub };
};
```

**중요**: 두 캘린더 페이지의 `getEventLabels`는 **이 한 곳만 의도적으로 갈라진다** (buyer ↔ seller). 다른 모든 코드는 두 파일에서 100% 동일.

`title` fallback 필수: 사용자가 수동 등록한 일정은 product_name이 null이라 title이 메인이 된다.
주문번호(`order_number`)는 더 이상 메인/서브 어디에도 노출하지 않는다 — 사용자에게 의미 없는 식별자라 제거. EventDetailModal/DayEventsModal 같은 상세 모달에서만 부가정보로 표시.

#### 캘린더 일정 색상/라벨 — order_status 필드 우선, event_type fallback (검증됨, 2026-04-27)

`getCalendarEventColorClass(event)` / `getCalendarEventLabel(event)` 두 함수가 `frontend/constants/status.ts`에 정의됨.
**텍스트 파싱(title/description) 레거시는 완전 제거됨** — 백엔드가 더 이상 상태 키워드를 텍스트에 넣지 않으므로 항상 fallback으로 떨어져 모든 주문 일정이 회색·"주문" 라벨로 보이는 버그가 있었음.

핵심 매핑 규칙:
- `event.order_status`가 있으면 `ORDER_STATUS_CONFIG[order_status].solidClassName / .label` 사용 → **주문/견적 페이지와 색·라벨 자동 일치**
- 없으면 `EVENT_TYPE_COLOR_CLASS[event_type] / EVENT_TYPE_LABEL[event_type]` fallback (MEETING은 보라, SHIPMENT는 파랑 등)

백엔드 트랩: 모든 주문 관련 일정의 `event_type`이 `'ORDER'`로 고정 송출되므로 `EVENT_TYPE_LABEL`만으로는 모든 일정이 "주문"으로 표시됨. **반드시 order_status 우선 매핑**.

```typescript
// constants/status.ts (실제 코드 발췌)
export function getCalendarEventColorClass(
  event: Pick<CalendarEvent, 'event_type' | 'order_status'>
): string {
  if (event.order_status && event.order_status in ORDER_STATUS_CONFIG) {
    return ORDER_STATUS_CONFIG[event.order_status].solidClassName;
  }
  return EVENT_TYPE_COLOR_CLASS[event.event_type] ?? EVENT_TYPE_COLOR_CLASS.OTHER;
}

export function getCalendarEventLabel(
  event: Pick<CalendarEvent, 'event_type' | 'order_status'>
): string {
  if (event.order_status && event.order_status in ORDER_STATUS_CONFIG) {
    return ORDER_STATUS_CONFIG[event.order_status].label;
  }
  return EVENT_TYPE_LABEL[event.event_type] ?? '기타';
}
```

호출부 (셀, 우측 리스트, EventDetailModal 모두 동일):
```tsx
// 라벨 (이전: EVENT_TYPE_OPTIONS.find(...)?.label — 모두 "주문"으로 보였음)
const typeLabel = getCalendarEventLabel(ev);

// 색 (이전: 텍스트 파싱 후 fallback이라 죄다 회색)
className={cn('...', getCalendarEventColorClass(ev))}
```

`ORDER_STATUS_CONFIG`의 `solidClassName`/`label`은 **주문/견적 페이지(StatusBadge)에서도 동일하게 사용**되므로 캘린더와 색·라벨이 자동으로 일관됨. `aliases` 필드와 텍스트 파싱 헬퍼(`getOrderStatusFromText`, `getOrderStatusFromCalendarEvent`, `ORDER_STATUS_MATCH_ORDER`, `normalizeStatusText`)는 모두 제거됨.

#### 정렬 — event_date asc, 동일 날짜는 start_time asc (검증됨)

```typescript
const sortedEvents = useMemo(() => {
  return [...events].sort((a, b) => {
    if (a.event_date !== b.event_date) return a.event_date.localeCompare(b.event_date);
    const aStart = a.start_time ?? '';
    const bStart = b.start_time ?? '';
    return aStart.localeCompare(bStart);
  });
}, [events]);
```

`event_date`는 'YYYY-MM-DD' 문자열, `start_time`은 'HH:MM:SS' 또는 null이라 `localeCompare`로 정렬해도 사전순=시간순으로 일치한다.

#### AI 패널 컴포넌트 디렉토리 위치

`components/calendar/` 디렉토리는 기본 생성 안 됨 — `mkdir -p`로 먼저 생성 후 파일 작성.

#### types/index.ts 배럴 파일 — 새 타입 추가 시 export 등록 필수 (함정)

`types/user.ts` 등에 새 인터페이스를 추가해도 `types/index.ts`에 export 라인을 추가하지 않으면
`@/types`로 임포트 시 `Module has no exported member` 컴파일 오류가 발생한다.
새 타입을 `types/*.ts`에 추가할 때는 반드시 `types/index.ts`도 함께 수정한다.

```typescript
// types/index.ts — 예시
export type { User, UserRole, UserPublicProfile } from './user';
//                             ^^^^^^^^^^^^^^^^^ 누락하면 컴파일 오류
```

#### 회원 검색 페이지 패턴 (검증됨)

`useMembers` + 탭바 + 카드 그리드 + 프로필 모달 + `useCreateChatRoom` 흐름:

```typescript
// hooks/useMembers.ts
// MemberFilters에 role 포함 — 프론트에서 명시적으로 역할을 선택해 전달
export function useMembers(filters?: { search?: string; page?: number; limit?: number; role?: string }) {
  return useQuery({
    queryKey: ['members', filters],
    queryFn: () => api.get<SuccessResponse<UserPublicProfile[]>>('/users/search', filters),
  });
}

export function useMemberProfile(userId: string | null) {
  return useQuery({
    queryKey: ['memberProfile', userId],
    queryFn: () => api.get<SuccessResponse<UserPublicProfile>>(`/users/${userId}/profile`),
    enabled: !!userId,
  });
}
```

탭바 패턴 (구매자/판매자 전환):
```typescript
// 탭 전환 시 검색어도 초기화해야 UX가 자연스럽다
type SearchRole = 'BUYER' | 'SELLER';
const [selectedRole, setSelectedRole] = useState<SearchRole>('BUYER'); // 판매자 페이지 기본값
const handleRoleChange = (role: SearchRole) => {
  setSelectedRole(role);
  setSearch(''); // 검색어 초기화
};

// 탭바 디자인: bg-gray-100 컨테이너, 선택된 탭은 bg-white shadow-sm text-primary-700
<div className="mb-6 inline-flex rounded-lg border border-gray-200 bg-gray-100 p-1">
  <button className="rounded-md px-5 py-2 text-sm font-medium ... bg-white text-primary-700 shadow-sm">구매자</button>
  <button className="rounded-md px-5 py-2 text-sm font-medium ... text-gray-500 hover:text-gray-700">판매자</button>
</div>
```

카드 그리드 패턴:
```tsx
// 이메일 표시 안 함 — 카드에도, 모달에도 이메일 항목 없음
// 아바타: 이미지 없으면 이름 첫 글자 원형 (bg-primary-100 text-primary-700)
// 카드 클릭 → 모달, 채팅하기 버튼 클릭 → e.stopPropagation() 후 채팅방 생성
<div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
  {members.map((member) => <MemberCard key={member.id} ... />)}
</div>
```

채팅 생성 후 라우팅 패턴:
```typescript
createChatRoom.mutate(
  { partner_user_id: userId },
  { onSuccess: () => { setSelectedUserId(null); router.push('/seller/chat'); } }
);
```

백엔드 `GET /users/search` — `role` 쿼리 파라미터:
- role 명시 시: 해당 역할(SELLER|BUYER)로 검색
- role 없으면: 요청자의 반대 역할로 fallback (기존 동작 유지)
- SELLER/BUYER 이외의 값은 400 에러 반환

#### 로그아웃 시 React Query 캐시 초기화 필수 (검증됨)

로그아웃 후 다른 계정으로 로그인하면 이전 계정의 캐시된 데이터(`chatRooms` 등)가 잠깐 노출되는 버그가 있다.
`useAuth.ts`의 `signOut` 함수와 `onAuthStateChange`의 `SIGNED_OUT` 핸들러 양쪽에서 반드시 `queryClient.clear()`를 호출해야 한다.

```typescript
// hooks/useAuth.ts
import { useQueryClient } from '@tanstack/react-query';

export function useAuth() {
  const queryClient = useQueryClient();

  // onAuthStateChange 핸들러
  if (event === 'SIGNED_OUT') {
    queryClient.clear();  // 모든 캐시 제거 → 새 사용자에게 이전 데이터 노출 방지
    logout();
    router.push('/login');
  }

  // signOut 함수
  const signOut = async () => {
    await supabase.auth.signOut();
    queryClient.clear();  // 동일하게 캐시 제거
    logout();
    router.push('/login');
  };
}
```

- `queryClient.clear()`는 모든 쿼리의 캐시를 완전 제거한다. `queryClient.invalidateQueries()`는 캐시를 남기므로 이 목적에 부적합.
- 두 곳 모두 추가해야 한다: `supabase.auth.signOut()` 호출 시 `SIGNED_OUT` 이벤트가 발생하지만, 명시적 `signOut` 함수에서도 즉시 처리하는 것이 안전하다.

#### 프로필 조회 순서: 백엔드 API 우선, Supabase fallback (검증됨)

`useAuth.ts`와 `login/page.tsx`에서 프로필을 조회할 때 Supabase 클라이언트(anon key)로 `users` 테이블을 직접 조회하면 RLS 정책에 막혀 프로필을 가져오지 못할 수 있다. 이로 인해 `user.id`가 빈 문자열로 세팅되어 채팅 메시지 색상 구분 등 `user.id` 의존 기능이 모두 깨진다.

올바른 패턴: `GET /api/v1/users/me`를 1순위로 호출하고, 실패 시에만 Supabase 직접 조회로 fallback.

```typescript
// 1순위: 백엔드 API (service_role로 조회 → RLS 우회, users.id 보장)
try {
  const result = await api.get<SuccessResponse<User>>('/users/me');
  setUser(result.data);  // id 포함 완전한 프로필
} catch (e) {
  // 2순위: Supabase 직접 조회 (anon key, RLS 적용됨)
  const { data: profile } = await supabase
    .from('users')
    .select('*')
    .eq('supabase_uid', supabaseUserId)
    .single();
  if (profile) setUser(profile as User);
  // 3순위: Auth 메타데이터 폴백 (id가 없어 기능 제한)
}
```

적용 위치: `hooks/useAuth.ts` (세션 동기화), `app/(auth)/login/page.tsx` (로그인 후 리다이렉트).

#### AI 히스토리 훅 패턴 (검증됨)

`useAIHistory` 훅은 `enabled: !!user`로 인증 후에만 실행한다. 백엔드 `/ai/history` 응답 필드는
`user_message`/`ai_response`가 **아닌** `prompt`/`response`임에 주의한다.

```typescript
// hooks/useAIHistory.ts
export interface AIConversation {
  id: string;
  user_id: string;
  prompt: string;       // ← user_message 아님
  response: string;     // ← ai_response 아님
  prompt_type: string | null;
  created_at: string;
}

export function useAIHistory(limit = 50) {
  const { user } = useAuthStore();
  return useQuery({
    queryKey: ['ai-history', limit],
    queryFn: () => api.get<SuccessResponse<AIConversation[]>>(`/ai/history`, { limit }),
    enabled: !!user,
    staleTime: 30_000,
  });
}
```

#### AI 어시스턴트 페이지 — 히스토리 + 날짜 구분선 패턴 (검증됨)

- 백엔드는 **최신순** 반환 → 페이지에서 `.reverse()`로 뒤집어 표시
- 날짜 구분선: 인접한 두 항목의 `created_at.slice(0, 10)` 비교
- 현재 세션 응답(useAIStream)은 히스토리 아래 별도로 렌더링, 날짜 구분선 추가

```tsx
const sortedHistory = [...history].reverse(); // 오래된순 정렬

{sortedHistory.map((conv, idx) => {
  const dateLabel = conv.created_at.slice(0, 10);
  const prevLabel = idx > 0 ? sortedHistory[idx - 1].created_at.slice(0, 10) : null;
  return (
    <div key={conv.id}>
      {dateLabel !== prevLabel && <DateDivider label={dateLabel} />}
      <div className="flex justify-end mb-2">  {/* 사용자: 오른쪽, bg-primary-100 */}
        <div className="max-w-[75%] rounded-2xl bg-primary-100 px-4 py-2 text-sm text-primary-900">
          {conv.prompt}
        </div>
      </div>
      <div className="flex justify-start mb-2">  {/* AI: 왼쪽, bg-gray-100 */}
        <div className="max-w-[75%] rounded-2xl bg-gray-100 px-4 py-2 text-sm text-gray-800 whitespace-pre-wrap">
          {conv.response}
        </div>
      </div>
    </div>
  );
})}
```

#### useAIStream — manualReview 플래그 (검증됨)

`useAIStream`이 `manualReview: boolean`을 추가로 반환한다.
백엔드 orchestrator `final_state.manual_review`가 `true`이면 페이지/패널에서 경고 배너를 표시한다.

```typescript
// hooks/useAIStream.ts — 반환값
return { response, isStreaming, manualReview, stream, abort, reset };

// 페이지에서 사용 (풀 사이즈 — text-sm)
const { response, isStreaming, manualReview, stream } = useAIStream();

{manualReview && (
  <div className="bg-yellow-50 border border-yellow-400 rounded p-3 mb-2 flex items-center gap-2">
    <AlertTriangle className="h-4 w-4 text-yellow-500 flex-shrink-0" aria-hidden="true" />
    <span className="text-yellow-800 text-sm">
      AI 답변 검토 필요 — 처리 중 이상이 감지됐습니다. 결과를 직접 확인해 주세요.
    </span>
  </div>
)}

// AIChatPanel(우측 좁은 패널)에서 사용 — 컴팩트 톤 (text-[11px])
// response 는 destructure 하지 않고 turns 기준으로 렌더하면서
// 마지막 turn 응답 직후에만 배너 노출
const lastTurn = turns.length > 0 ? turns[turns.length - 1] : null;
const showManualReviewBanner = manualReview && !!lastTurn && !lastTurn.pending;
```

백엔드 orchestrator.py `run()` return에도 `manual_review` 필드를 포함해야 한다:
```python
return {
    "response": final_state.get("final_response") or "응답을 생성하지 못했습니다.",
    "tools_used": final_state.get("tools_used", []),
    "manual_review": final_state.get("manual_review", False),  # ← 필수
}
```

#### 대시보드 미확인 채팅 카운트 연동 패턴 (검증됨)

`useChatRooms()`의 데이터에서 `unread_count`를 합산한다.
`ChatRoom` 타입 어노테이션을 명시해야 `reduce` 타입 추론이 정확하다.

```typescript
import { useChatRooms } from '@/hooks/useChat';
import type { ChatRoom } from '@/types';

const { data: roomsData } = useChatRooms();
const rooms: ChatRoom[] = roomsData?.data ?? [];
const unreadTotal = rooms.reduce((sum, r) => sum + (r.unread_count ?? 0), 0);

<SummaryCard title="미확인 채팅" value={unreadTotal} ... />
```

#### useProducts 서버 측 필터 패턴 (검증됨)

`ProductFilters`에 백엔드 쿼리 파라미터를 모두 포함시키고, browse 페이지에서 state 값을 훅에 직접 전달한다.
`queryKey: ['products', filters]`는 filters 객체 전체를 포함하므로 `max_price`/`min_stock` 추가만으로 state 변경 시 자동 refetch된다. 별도 queryKey 수정 불필요.

```typescript
// hooks/useProducts.ts
interface ProductFilters {
  category?: string;
  product_status?: string;
  seller_id?: string;
  search?: string;
  page?: number;
  limit?: number;
  max_price?: number;  // 백엔드 쿼리 파라미터
  min_stock?: number;  // 백엔드 쿼리 파라미터
}

export function useProducts(filters?: ProductFilters) {
  return useQuery({
    queryKey: ['products', filters],  // filters 전체가 키 → 어떤 필드 추가해도 자동 반영
    queryFn: () =>
      api.get<SuccessResponse<Product[]>>('/products', filters as Record<string, unknown>),
  });
}
```

browse 페이지에서 state → 훅 전달 (클라이언트 filter() 제거):
```typescript
// 빈 문자열은 undefined로 변환해야 백엔드가 해당 파라미터를 무시함
const { data, isLoading } = useProducts({
  search: search || undefined,
  category: categoryFilter || undefined,
  max_price: maxPrice ? Number(maxPrice) : undefined,
  min_stock: minStock ? Number(minStock) : undefined,
});
const filtered = data?.data ?? [];  // 서버가 필터링한 결과 그대로 사용
```

- 클라이언트 `products.filter()` useMemo 제거 — 페이지네이션 시 전체 데이터 없어도 서버가 정확히 필터링
- `'' || undefined` 패턴 필수: 빈 문자열을 그대로 보내면 백엔드가 빈 값으로 필터링함

#### useOrders status_in 다중값 + 탭별 서버 필터링 (검증됨, 2026-04-27)

주문/견적 페이지(`seller/orders`, `buyer/orders`)는 탭마다 백엔드를 다시 호출해 해당 상태만 받는다.
**`useOrders()` 인자 없이 호출 → `allOrders.filter(...)` 클라이언트 필터링 패턴 금지** — 첫 20개에만 필터가 적용되어 "최근 20개 중 완료된 주문만" 보여주는 버그 발생.

```typescript
// hooks/useOrders.ts
interface OrderFilters {
  order_status?: OrderStatus;
  status_in?: OrderStatus[];        // 다중 상태 필터 — 백엔드 GET /orders 의 status_in 다중 query 와 매핑
  partner_user_id?: string;         // V1.7 — 양방향 거래처 필터 (me ↔ partner_user_id 사이의 주문만)
  page?: number;
  limit?: number;
}
```

페이지에서 활성 탭의 statuses 만 서버에 전달:
```typescript
const activeStatuses = tabs.find((t) => t.key === activeTab)?.statuses ?? [];
const { data: listData, isLoading } = useOrders({
  status_in: activeStatuses,
  limit: 2000,   // 사실상 전체
});
const filteredOrders = listData?.data ?? [];   // 서버가 필터링한 결과 그대로
```

- 탭 전환 시 React Query `queryKey: ['orders', filters]` 가 `status_in` 배열 변화로 자동 refetch
- 카운트 뱃지: 활성 탭만 `(N)` 표시 (서버에서 비활성 탭의 카운트를 한 번에 알 수 없으므로 비활성 탭은 카운트 생략)
- 데이터 테이블은 `<div className="max-h-[calc(100vh-280px)] overflow-y-auto rounded-xl">` 로 감싸서 헤더 위치 고정 + 본문 스크롤

#### orders 페이지 — partner_user_id 필터 chip 패턴 (검증됨, 2026-04-28, V1.7)

거래처 페이지 "최근 거래" 컬럼 클릭 시 `/{role}/orders?partner_user_id=<uuid>` 로 진입한다.
주문 페이지에서 `searchParams.get('partner_user_id')` 로 읽어 `useOrders({ partner_user_id })` 에 전달.

- **정기배송 탭에는 적용하지 않음** — 정기배송은 `useSubscriptions` 별도 흐름이므로 `isSubTab ? undefined : partnerFilter` 로 가드.
- 거래처 이름 lookup: `usePartners()` (인자 없음) 결과에서 `partner_user_id` 매칭. fallback 은 `'특정 거래처'`.
  - 이미 정기배송 탭의 `PartnerDetailModal` 매핑용으로 호출 중이라 별도 호출 불필요.
- chip UI 는 정기배송 탭에서는 미노출 (`!isSubTab && partnerFilter`), 탭 위에 위치:

```tsx
{!isSubTab && partnerFilter && (
  <div className="mb-3 flex flex-wrap items-center gap-2">
    <span className="text-xs text-gray-500">필터:</span>
    <button
      type="button"
      onClick={() => router.push('/buyer/orders')}   // partner_user_id 빠진 URL 로 이동
      className="inline-flex items-center gap-1 rounded-full bg-primary-50 px-3 py-1 text-xs text-primary-700 hover:bg-primary-100"
      title="필터 해제"
    >
      거래처: {filteredPartnerLabel}
      <X className="h-3 w-3" />
    </button>
  </div>
)}
```

#### usePartners — include_last_trade 옵션 (검증됨, 2026-04-28, V1.7)

`PartnerFilters` 에 `include_last_trade?: boolean` 추가. 백엔드 GET /partners 는 기본 false 로 last_trade_date / last_trade_amount 를 응답에 포함하지 않는다 (집계 비용 보호). 거래처 페이지에서만 명시적으로 true 로 호출.

```typescript
// 거래처 페이지 (last_trade 컬럼 노출 필요)
const { data } = usePartners({
  partner_status: ...,
  search: ...,
  include_last_trade: true,
});

// 다른 페이지 (orders 정기배송 매핑, members, subscriptions, AddPartnerModal 등) — 인자 없이 호출 유지
const { data } = usePartners();
```

**주의 — React Query 캐시 분리**: queryKey 가 `['partners', filters]` 라서 `usePartners({ include_last_trade: true })` 와 `usePartners()` 는 별도 캐시 슬롯을 차지한다. 거래처 페이지(last_trade 포함)와 다른 페이지(last_trade 없음)가 같은 사용자 세션에서 두 번 fetch 되는 trade-off 가 발생하지만, 다른 페이지에서 불필요한 집계 비용을 피하는 설계 의도와 일치한다.

#### 거래처 행 빠른 액션 — 정기배송 신청 진입점 (검증됨, 2026-05-04, 테스터 피드백 #6)

거래처 목록 페이지에서 `PartnerDetailModal` 을 열지 않고도 정기배송 신청 모달을 직접 호출하는 빠른 액션 버튼. 발견성 ↑.

- **노출 조건**: `item.status === 'ACTIVE'` 만 — `PENDING_*` / `INACTIVE` 거래처는 버튼 자체 미노출.
- **상태 모델**: `useState<Partner | null>(subscriptionPartner)` 한 개로 모달 가시성과 prefill 대상 partner 를 동시에 관리.
- **prefill 방식**: `SubscriptionFormModal` 은 별도의 prefill prop 이 없어도 `partner` prop 만으로 `seller_id` / `buyer_id` / `partner_id` 자동 매핑 (myRole 기준 분기). 추가 prop 신설 불필요.
- **버튼 패턴** (양쪽 페이지 actions 컬럼 동일):

```tsx
{item.status === 'ACTIVE' && (
  <button
    onClick={(e) => {
      e.stopPropagation();          // 행 onClick (PartnerDetailModal 열기) 차단 필수
      setSubscriptionPartner(item);
    }}
    title="정기배송 신청"
    className="inline-flex items-center gap-1 rounded-lg border border-primary-600 bg-white px-2.5 py-1 text-xs font-medium text-primary-700 hover:bg-primary-50"
  >
    <Repeat className="h-3.5 w-3.5" />
    <span className="hidden sm:inline">정기배송</span>
  </button>
)}
```

- **모바일 대응**: 라벨 텍스트는 `hidden sm:inline` 으로 작은 화면(≤640px)에서 아이콘만 노출. actions 컨테이너는 `flex flex-wrap items-center justify-end gap-1` 로 폭이 부족할 때 줄바꿈. (기존 `채팅` / `주문 작성` 버튼도 같은 정책으로 통일했음)
- **모달 렌더 위치**: 페이지 최하단 `PartnerDetailModal` 옆에 conditional 렌더 (`subscriptionPartner && <SubscriptionFormModal .../>`).
- **아이콘 선택**: `Repeat` (lucide). 정기성/반복 의미가 가장 자연스러움. `RefreshCw` 는 새로고침과 혼동, `CalendarRange` 는 일정 의미가 강함.

#### lib/api.ts 배열 query param 직렬화 (검증됨, 2026-04-27)

FastAPI `Query(None)` 다중값은 `?key=A&key=B` (repeat) 형식을 기대한다. axios 기본은 `?key[]=A&key[]=B` 라 호환 안 됨.
이 프로젝트의 `lib/api.ts`는 fetch 기반이며, `api.get(path, params)` 의 `Object.entries(params)` 루프에서 `Array.isArray(v)` 분기로 `searchParams.append(k, ...)` 를 반복 호출해 repeat 직렬화한다. 단일 값은 기존대로 `searchParams.append(k, String(v))`.

```typescript
// lib/api.ts api.get
Object.entries(params).forEach(([k, v]) => {
  if (v == null) return;
  if (Array.isArray(v)) {
    v.forEach((x) => { if (x != null) searchParams.append(k, String(x)); });
  } else {
    searchParams.append(k, String(v));
  }
});
```

훅 측에서는 별도 직렬화 없이 그냥 `{ status_in: ['COMPLETED', 'CANCELLED'] }` 처럼 배열을 넘기면 된다. `qs` 라이브러리 의존성 없음.

#### browse "문의" → 채팅방 생성 → 시스템 메시지 → 라우팅 패턴 (검증됨)

`[문의]` 버튼 전용 흐름. 견적 요청은 별도 모달로 분리됨(위 섹션 참조).

```typescript
// 1. 채팅방 생성 (product.seller_id → partner_user_id)
const roomRes = await createChatRoom.mutateAsync({ partner_user_id: product.seller_id });
const roomId = roomRes.data.id;

// 2. 시스템 메시지 발송 — 라벨은 [상품 문의] (견적이 아니므로 구분)
await sendMessage.mutateAsync({
  roomId,
  content: `[상품 문의] 상품: ${product.name} (${categoryLabel}) / 단가: ${product.price_per_unit.toLocaleString()}원/${product.unit}`,
});

// 3. 채팅 페이지 이동 (room_id 쿼리스트링)
router.push(`/buyer/chat?room_id=${roomId}`);
```

채팅 페이지에서 room_id 쿼리스트링 자동 선택:
```typescript
// buyer/chat/page.tsx
const searchParams = useSearchParams();
useEffect(() => {
  const roomIdParam = searchParams.get('room_id');
  if (roomIdParam) {
    setSelectedRoomId(roomIdParam);
    setMobileView('messages');
  }
}, [searchParams]);
```

#### 시스템 메시지 렌더링 패턴 (검증됨)

`[견적 요청]` 등 `[` 시작 + `]` 포함 내용은 시스템 메시지로 판별해 가운데 회색 pill로 표시한다.

```tsx
const isSystem = msg.content.startsWith('[') && msg.content.includes(']');
if (isSystem) {
  return (
    <div key={msg.id} className="flex justify-center">
      <div className="rounded-full bg-gray-100 px-4 py-1 text-xs text-gray-500">
        {msg.content}
      </div>
    </div>
  );
}
```

#### useMessagesWithWebSocket — alternativePartnersSuggestion 노출 (검증됨)

`lastMessage.type === 'alternative_partners_suggestion'`인 경우 훅에서 별도로 추출해 반환한다.
채팅 페이지에서 배너로 표시한다.

```typescript
// hooks/useChat.ts
const alternativePartnersSuggestion =
  lastMessage?.type === 'alternative_partners_suggestion' ? lastMessage : null;

return { messageQuery, isConnected, sendMessage, wsError, alternativePartnersSuggestion };

// 채팅 페이지에서
const { ..., alternativePartnersSuggestion } = useMessagesWithWebSocket(selectedRoomId);

{alternativePartnersSuggestion && (
  <div className="flex items-center gap-2 border-b border-yellow-200 bg-yellow-50 px-4 py-2">
    <AlertTriangle className="h-4 w-4 flex-shrink-0 text-yellow-500" aria-hidden="true" />
    <p className="flex-1 text-xs text-yellow-800">
      대체 거래처가 제안됐습니다. 거래처 목록에서 확인해 보세요.
    </p>
  </div>
)}
```

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

#### 주문/견적 도메인 — 입력 타입 통합 패턴 (검증됨)

백엔드 Pydantic의 `OrderItemCreate` / `OrderItemUpdate` / `CounterOffer.proposed_items`가
모두 동일한 구조(`product_id`, `quantity`, `unit_price`, `notes?`)이므로
프론트에서는 **단일 `OrderItemInput`** 에 매핑한다. 기존 코드 호환을 위해
`OrderItemCreate`는 별칭으로 유지한다.

```typescript
// types/order.ts
export interface OrderItemInput {
  product_id: string;
  quantity: number;
  unit_price: number;
  notes?: string;
}
// 기존 import 호환 (구상품 페이지 등)
export type OrderItemCreate = OrderItemInput;
```

`types/index.ts` 배럴 파일에 `OrderItemInput`, `OrderUpdate`, `CounterOffer`,
`CounterOfferCreate`, `CounterOfferStatus`, `FromRole` 추가 export 필요.

#### 주문 상세 — useOrder 별도 쿼리 + invalidate 키 분리 (검증됨)

목록(`['orders']`)과 상세(`['order', orderId]`)를 분리해 캐싱한다.
상세는 액션(상태 변경/협상 제시·수락·거절/취소) 직후 자동 refetch가 필요하므로 모든 mutation의 `onSuccess`에서 두 키를 함께 invalidate한다.

```typescript
// hooks/useOrders.ts — 모든 단건 액션 mutation
onSuccess: (_, variables) => {
  queryClient.invalidateQueries({ queryKey: ['orders'] });
  queryClient.invalidateQueries({ queryKey: ['order', variables.id] });
  queryClient.invalidateQueries({ queryKey: ['negotiation', variables.id] });
}
```

페이지에서는 `selectedOrderId` 상태로 슬라이드 패널에 띄울 주문을 선택하고,
`useOrder(selectedOrderId)`로 최신 상세를 받으며 목록 데이터로 fallback 한다:

```typescript
const { data: detailData } = useOrder(selectedOrderId ?? '');
const selectedOrder: Order | null =
  detailData?.data ??
  (selectedOrderId
    ? allOrders.find((o) => o.id === selectedOrderId) ?? null
    : null);
```

#### 협상 이력 — 본인/상대 판별로 액션 노출 가드 (검증됨)

`useNegotiationHistory(orderId)`로 받은 협상가 목록에서
**가장 최근의 PENDING 항목**이 상대방 제시이면 수락/거절 노출,
본인 제시이면 "상대방 응답 대기 중"만 표시한다.

```tsx
const latestPending = sorted.find((o) => o.status === 'PENDING');
const canRespond =
  latestPending &&
  user &&
  latestPending.from_user_id !== user.id &&  // 상대방 제시건만
  (orderStatus === 'QUOTE_REQUESTED' || orderStatus === 'NEGOTIATING');
```

`from_role`(SELLER/BUYER)은 배지 표시용. 인증된 사용자 ID와의 비교는
반드시 `from_user_id` 사용 — `from_role`만으로 본인/상대 판별 금지(같은 역할 두 사용자가 있을 수 있음).

#### 납품일 변경 섹션 — NegotiationHistory 와 동일 패턴 (검증됨, 2026-04-29)

`components/common/DeliveryDateChangeSection.tsx` 가 주문 상세 슬라이드 패널의 `<NegotiationHistory />` **바로 아래**에 배치된다 (buyer/seller 양 페이지). props:
```ts
interface DeliveryDateChangeSectionProps {
  orderId: string;
  orderStatus: OrderStatus;
  currentDeliveryDate: string | null;
}
```

핵심 동작:
- `QUOTE_REQUESTED`/`NEGOTIATING`/`CONFIRMED` 일 때만 "변경 요청" 버튼 + 인라인 폼 노출
- `PREPARING` 이상이면 "출하 준비 중이라 납품일을 변경할 수 없습니다" 안내 박스
- 가장 최근 PENDING 이 상대방 제안이면 수락/거절 버튼 (NegotiationHistory 와 동일 가드, **CONFIRMED 도 응답 가능**)
- 수락 시 `useAcceptDeliveryDateChange` 가 `['calendar']` 도 invalidate → 캘린더 자동 동기화

훅은 `hooks/useDeliveryDateChanges.ts` (4개 export): `useDeliveryDateChanges` / `useSubmitDeliveryDateChange` / `useAcceptDeliveryDateChange` / `useRejectDeliveryDateChange`. 모두 `orderId` argument.

#### 판매자 vs 구매자 — 상태 전이 권한 매트릭스 (검증됨, 2026-04-27 갱신)

백엔드 역할 가드가 일부 완화되어 양쪽 모두 가능한 전이가 늘었다.
다음 상태 버튼이 자동 노출되지 않는 전이는 **명시적 액션 버튼**으로 노출한다 (예: 판매자의 "주문 확정", 구매자의 "수령 완료").

| 상태 | BUYER | SELLER |
|---|---|---|
| `QUOTE_REQUESTED → CONFIRMED` | O | O (신규) |
| `NEGOTIATING → CONFIRMED` | O | O |
| `CONFIRMED → PREPARING` | X | O |
| `PREPARING → SHIPPING` | X | O |
| `SHIPPING → COMPLETED` | O (신규) | O |
| 취소 | O | O |

판매자 next-status 맵 (자동 "다음 상태로 진행" 버튼용 — 일반적인 단일 다음 상태만):
```typescript
// seller/orders/page.tsx
const sellerNextStatusMap: Record<string, OrderStatus> = {
  CONFIRMED: 'PREPARING',
  PREPARING: 'SHIPPING',
  SHIPPING: 'COMPLETED',
};
```

`QUOTE_REQUESTED`/`NEGOTIATING`은 sellerNextStatusMap에 넣지 않는다 — "주문 확정" 명시 버튼이 더 직관적이므로 별도 버튼으로 분리:

```tsx
{counterOfferableStatuses.includes(selectedOrder.status) && (
  <button
    onClick={() => updateStatus.mutate({ id: selectedOrder.id, status: 'CONFIRMED' })}
    disabled={updateStatus.isPending}
    className="rounded-lg bg-primary-600 px-3 py-2 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50"
  >
    주문 확정
  </button>
)}
```

구매자 페이지도 마찬가지로 `SHIPPING → COMPLETED`는 명시 버튼으로 노출하고 안내 텍스트를 함께 표시:
```tsx
{selectedOrder.status === 'SHIPPING' && (
  <p className="mb-2 text-xs text-gray-500">물건을 받으셨다면 완료 처리해 주세요</p>
)}
{selectedOrder.status === 'SHIPPING' && (
  <button onClick={() => updateStatus.mutate({ id: selectedOrder.id, status: 'COMPLETED' })} ...>
    수령 완료
  </button>
)}
```

구매자 페이지에서 `useUpdateOrderStatus` 임포트 누락 함정: 기존 구매자 페이지는 상태 변경이 없어서 import가 빠져있었다. SHIPPING → COMPLETED 추가 시 반드시 추가.

#### 주문 목록/상세 — 백엔드 join 평탄화 필드 활용 (검증됨)

백엔드가 `Order` 응답에 `buyer_name`/`buyer_company`/`seller_name`/`seller_company`,
`OrderItem` 응답에 `product_name`/`product_unit`/`product_category`를 평탄화해 내려준다.
모두 `string | null | undefined` (사용자/상품 soft-delete 시 null).

**목록 첫 컬럼 패턴 — 상품명 메인 / 주문번호 서브:**
```tsx
{
  key: 'product',
  header: '상품',
  render: (item) => {
    const firstName = item.items?.[0]?.product_name ?? '상품 정보 없음';
    const extra = item.items.length > 1 ? ` 외 ${item.items.length - 1}건` : '';
    return (
      <div className="flex flex-col">
        <span className="font-medium text-gray-900">{firstName}{extra}</span>
        <span className="text-xs text-gray-500">{item.order_number}</span>
      </div>
    );
  },
},
```

**상대방 컬럼 (구매자 페이지에는 판매자, 판매자 페이지에는 구매자):**
```tsx
{
  key: 'seller',  // 또는 'buyer'
  header: '판매자',  // 또는 '구매자'
  render: (item) => (
    <div className="flex flex-col">
      <span className="text-sm text-gray-900">{item.seller_name ?? '-'}</span>
      {item.seller_company && (
        <span className="text-xs text-gray-500">{item.seller_company}</span>
      )}
    </div>
  ),
},
```

**상세 슬라이드 헤더 — 상품 요약 한 줄 + 주문번호 서브 + 상대방 한 줄:**
```tsx
<div className="flex items-start justify-between border-b border-gray-200 px-6 py-4">
  <div className="min-w-0 flex-1 pr-3">
    {(() => {
      const firstItem = selectedOrder.items?.[0];
      const firstName = firstItem?.product_name ?? '상품 정보 없음';
      const qtyUnit = firstItem ? ` ${firstItem.quantity}${firstItem.product_unit ?? ''}` : '';
      const extra = selectedOrder.items.length > 1 ? ` 외 ${selectedOrder.items.length - 1}건` : '';
      return (
        <h2 className="truncate text-lg font-semibold text-gray-900">
          {firstName}{qtyUnit}{extra}
        </h2>
      );
    })()}
    <p className="mt-0.5 truncate text-xs text-gray-500">{selectedOrder.order_number}</p>
    <p className="mt-1 truncate text-xs text-gray-600">
      판매자: {selectedOrder.seller_name ?? '-'}
      {selectedOrder.seller_company ? ` (${selectedOrder.seller_company})` : ''}
    </p>
  </div>
  <button onClick={closeDetail} className="flex-shrink-0 ...">닫기</button>
</div>
```

- 헤더는 `items-start` (헤더가 3줄로 늘어나므로) + `min-w-0 flex-1` + 닫기 버튼은 `flex-shrink-0` — 긴 상품명 truncate 보장.
- 상세 항목 카드에도 `<p className="mb-1 font-medium text-gray-900">{item.product_name ?? '상품 정보 없음'}</p>` 라인을 맨 위에 추가하면 어떤 상품인지 즉시 파악 가능.
- 수량 표시에 `{item.product_unit ?? ''}`를 붙여 "수량 10kg × ..." 형태로 자연스럽게 단위 노출.

#### 견적 생성 모달 — 검색형 판매자 선택 (검증됨, 2026-04-27 갱신)

**도메인 정의**: `partners` = 정기배송 관계, **주문/견적 = 일회성 거래** (거래처 등록과 무관).
따라서 견적 모달은 `usePartners`에 **의존하지 않는다**. 대신 `useMembers({role: 'SELLER'})` 로 전체 판매자를 typeahead 검색.

```typescript
// CreateOrderModal.tsx — 검색형 dropdown 패턴
const [sellerSearch, setSellerSearch] = useState('');
const [debouncedSearch, setDebouncedSearch] = useState('');

// 디바운스 300ms
useEffect(() => {
  const handle = setTimeout(() => setDebouncedSearch(sellerSearch), 300);
  return () => clearTimeout(handle);
}, [sellerSearch]);

const membersQuery = useMembers({
  role: 'SELLER',
  search: debouncedSearch || undefined,  // 빈 문자열은 undefined로 → 초기 20명 fetch
  page: 1,
  limit: 20,
});
```

UI 패턴:
- **선택 전**: 검색 input + absolute dropdown (외부 클릭 시 닫기 — useRef + mousedown)
- **선택 후**: `bg-primary-50` 카드 + 이름(회사명) 표시 + "변경" 버튼 → 다시 검색 모드 복귀

**판매자 변경 시 항목 초기화 — `useRef` 기반 prevId 비교 패턴 권장**:
모달이 열릴 때 `initialItem`으로 prefill한 첫 항목까지 함께 날리지 않으려면, 단순 `useEffect([sellerId])` 대신 prev/현재 값 비교가 필요하다.

```typescript
const prevSellerIdRef = useRef<string>('');
useEffect(() => {
  if (!isOpen) return;
  if (prevSellerIdRef.current && prevSellerIdRef.current !== sellerId) {
    setItems([{ ...emptyItem }]);  // 사용자가 판매자를 "변경"한 경우에만 초기화
  }
  prevSellerIdRef.current = sellerId;
}, [sellerId, isOpen]);
```

**Props**: `initialSellerId?`, `initialSellerName?` (라벨 즉시 표시용), `initialItem?: { product_id; quantity?; unit_price? }` 로 상품 카드 → 견적 모달 prefill 흐름 지원.

상품 select는 그대로 `useProducts({ seller_id: sellerId, limit: 200 })` 사용. seller_id 단수 컬럼이므로 다른 SELLER 상품 섞기 자연 차단.

#### browse 페이지 — 문의(채팅) + 견적 요청(모달) 분리 (검증됨)

상품 카드 액션을 두 버튼으로 분리하여 의도를 명확히 구분.
- `[문의]` (MessageCircle, outline 스타일): 채팅방 생성 + `[상품 문의]` 시스템 메시지 + `/buyer/chat?room_id=...` 라우팅
- `[견적 요청]` (FileText, primary 스타일): `CreateOrderModal` 오픈 (해당 상품을 첫 항목에 prefill)

```tsx
const [orderModalProduct, setOrderModalProduct] = useState<Product | null>(null);

<CreateOrderModal
  isOpen={!!orderModalProduct}
  onClose={() => setOrderModalProduct(null)}
  initialSellerId={orderModalProduct?.seller_id}
  initialItem={
    orderModalProduct
      ? { product_id: orderModalProduct.id, quantity: 1, unit_price: orderModalProduct.price_per_unit }
      : undefined
  }
/>
```

이전 패턴(견적 요청 = 채팅방 생성)은 **폐기됨**: 새 주문/견적 시스템과 연결되지 않아 결제/협상 흐름을 못 탔다. 채팅 흐름은 `[문의]`로 흡수.

---

#### 거래처(Partner) V1 UI 패턴 (검증됨, 2026-04-27)

거래처 페이지(seller/buyer)와 회원 검색 페이지(seller/buyer)에 거래처 등록 흐름이 통합되어 있다. **seller/buyer byte-identical** 패턴 — 두 역할의 페이지는 myRole 값과 라우트 prefix 만 다르고 컴포넌트 구조/UI 전부 동일하다.

##### usePartners 훅 확장 (`hooks/usePartners.ts`)

```typescript
// 즐겨찾기 토글 — 내부적으로 PATCH /partners/{id} { is_favorite }
export function useTogglePartnerFavorite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, is_favorite }: { id: string; is_favorite: boolean }) =>
      api.patch<SuccessResponse<Partner>>(`/partners/${id}`, { is_favorite }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['partners'] }),
  });
}

// 회원 검색 페이지에서 "이미 거래처" 표시용 — usePartners() 와 동일 queryKey 캐시 공유
export function usePartnerUserIdSet(): Set<string> {
  const { data } = usePartners();
  return useMemo(
    () => new Set((data?.data ?? []).map((p) => p.partner_user_id)),
    [data]
  );
}
```

`usePartnerUserIdSet()` 은 인자 없이 `usePartners()` 를 호출 → `queryKey: ['partners', undefined]` 가 거래처 페이지의 `['partners', { partner_status, search }]` 와 다른 캐시이지만, 거래처 추가/삭제 시 `invalidateQueries({ queryKey: ['partners'] })` 가 둘 다 무효화하므로 일관성이 유지된다. **즉시 동기화**: 회원 검색 페이지에서 "거래처 추가" → React Query mutation onSuccess → invalidate → 같은 페이지의 partnerUserIdSet 도 자동 refetch → 카드가 즉시 "거래처 등록됨" 으로 전환.

##### AddPartnerModal (`components/partners/AddPartnerModal.tsx`)

거래처 페이지의 "+ 거래처 추가" 버튼 클릭 시 오픈되는 모달. 검색 input + 결과 리스트 + 카드별 "추가" 버튼 구조. **V1에서는 nickname 입력 생략** — 회사명/이름 그대로 거래처로 등록되며, 별칭 편집 UI 는 V1.5 로 미룸.

Props:
```typescript
interface AddPartnerModalProps {
  isOpen: boolean;
  onClose: () => void;
  myRole: 'SELLER' | 'BUYER';   // 본인 역할 — 검색은 oppositeRole 만
}
```

내부 동작:
- `oppositeRole = myRole === 'SELLER' ? 'BUYER' : 'SELLER'`
- 검색은 엔터 또는 검색 버튼 클릭 시에만 트리거 — 입력 디바운스 없이 명시적 트리거 패턴
- `useMembers({ search, role: oppositeRole })` + 클라이언트 폴백 필터(`m.role === oppositeRole`) — 백엔드 role 필터가 미반영 시 안전장치
- `usePartnerUserIdSet()` 으로 이미 거래처면 "거래처 등록됨" 뱃지로 대체 (버튼 숨김)
- 추가 성공 → React Query invalidate → 그 자리에서 즉시 뱃지로 전환 (모달 자체는 사용자가 닫을 때까지 유지)

##### 회원 검색 페이지 — MemberCard 거래처 버튼

`app/(dashboard)/{seller,buyer}/members/page.tsx` MemberCard 컴포넌트:
- props 에 `myRole`, `isPartner`, `isAddingPartner`, `onAddPartner` 추가
- `canAddPartner = member.role !== myRole && member.role !== 'ADMIN'` — 본인과 같은 역할 또는 ADMIN 인 경우 거래처 추가 버튼 숨김
- 채팅하기 버튼 위에 "거래처 추가" 버튼 배치 (outline primary 스타일)
- 이미 거래처면 회색 "거래처 등록됨" 뱃지로 대체

페이지 레벨 상태:
```typescript
const [addingPartnerId, setAddingPartnerId] = useState<string | null>(null);
const createPartner = useCreatePartner();
const partnerUserIdSet = usePartnerUserIdSet();

const handleAddPartner = (userId: string) => {
  if (addingPartnerId || partnerUserIdSet.has(userId)) return;
  setAddingPartnerId(userId);
  createPartner.mutate({ partner_user_id: userId }, {
    onSettled: () => setAddingPartnerId(null),
  });
};
```

##### 거래처 페이지 — 즐겨찾기 우선 정렬 + 빠른 액션

`app/(dashboard)/{seller,buyer}/partners/page.tsx` 핵심:

1. **서버 사이드 필터로 통일** — 이전 buyer 페이지는 클라이언트 필터링이었으나 seller 와 동일하게 `usePartners({ partner_status, search })` 패턴으로 일치시킴
2. **즐겨찾기 우선 정렬** — `is_favorite desc → created_at desc`:
   ```typescript
   const sortedPartners = [...partners].sort((a, b) => {
     if (a.is_favorite !== b.is_favorite) return a.is_favorite ? -1 : 1;
     return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
   });
   ```
3. **PageHeader action 슬롯에 "+ 거래처 추가" 버튼** → `AddPartnerModal` 오픈
4. **빠른 액션 컬럼** — 행 우측에 채팅/주문 버튼:
   - 채팅: `useCreateChatRoom({ partner_user_id })` → `/{role}/chat?room_id=${res.data.id}` 라우팅
   - 주문 작성:
     - **buyer**: `/buyer/browse?seller_id=${partner_user_id}` 로 라우팅 (browse 페이지가 sellerFilter state 로 받아 useProducts 의 seller_id 인자에 전달)
     - **seller**: `/seller/orders/new` 페이지가 V1 에 존재하지 않음 → `showCreateOrderAction = false` 로 버튼 숨김 (V1.5 에서 추가 예정)

##### buyer/browse 페이지 — ?seller_id 쿼리 처리

`useSearchParams()` + state 동기화로 처리:
```typescript
const searchParams = useSearchParams();
const [sellerFilter, setSellerFilter] = useState<string | null>(null);

useEffect(() => {
  setSellerFilter(searchParams.get('seller_id'));
}, [searchParams]);

const { data } = useProducts({
  // 기존 필터들 ...
  seller_id: sellerFilter || undefined,
});

const clearSellerFilter = () => {
  setSellerFilter(null);
  router.replace('/buyer/browse');
};
```

`useProducts` 훅은 이미 `seller_id` 필터를 받고 백엔드 `GET /products` 도 이를 지원하므로 추가 변경 불필요. URL 에 `?seller_id=...` 가 있을 때 페이지 상단에 primary-50 배너로 "특정 거래처의 상품만 표시 중입니다 / [전체 보기]" 표시.

##### 빠른 액션 라우팅 매트릭스

| 위치 | 채팅 시작 | 주문 작성 |
|------|---------|---------|
| seller/partners | `/seller/chat?room_id=${id}` | **숨김** (V1) |
| buyer/partners | `/buyer/chat?room_id=${id}` | `/buyer/browse?seller_id=${id}` |

---

#### 정기배송(Subscription) V1.5 Phase 2 UI 패턴 (검증됨, 2026-04-27)

거래처 행 클릭 시 `PartnerDetailModal` 이 열리고, 그 안에서 정기배송 목록/생성/일시정지/주문 즉시 생성 등 모든 액션을 처리한다. seller/buyer **byte-identical** 페이지 구조 유지.

##### 백엔드 응답 컬럼 추가
- `OrderResponse.subscription_id: Optional[UUID]` / `subscription_round: Optional[int]` 추가 — 일반 주문은 None, 정기배송 자동 생성 주문은 값 채워짐. 프론트 `Order` 타입에도 동일 필드를 옵셔널로 추가.

##### 신규 타입/훅 정리
- `types/subscription.ts`: `Subscription`, `SubscriptionItem`, `SubscriptionItemCreate`, `SubscriptionCreate`, `SubscriptionUpdate`, `SubscriptionFrequency`, `SubscriptionStatus`, `PartnerStats` (PartnerStats도 같은 파일에 둠 — 다른 도메인에서 import 일관성 위해)
- `hooks/useSubscriptions.ts`: `useSubscriptions(filters)`, `useSubscription(id)`, `useCreateSubscription`, `useUpdateSubscription(id)`, `useDeleteSubscription`, `useGenerateSubscriptionOrder`
- `hooks/usePartners.ts`에 `usePartnerStats(partnerId)` 추가
- 모든 정기배송 mutation은 `onSuccess`에서 `['subscriptions']` + `['partner-stats']` (해당하는 경우 `['orders']`/`['calendar']`까지) invalidate

##### Modal `xl` size 추가
`Modal.tsx`에 `size: 'xl'` (max-w-3xl) 옵션을 추가. 큰 상세 모달(PartnerDetailModal, SubscriptionFormModal)에서 사용. 기존 `'sm' | 'md' | 'lg'`는 그대로 유지.

##### PartnerDetailModal 구조 (`components/partners/PartnerDetailModal.tsx`)
- **Props**: `partner: Partner | null`, `myRole: 'SELLER' | 'BUYER'`, `onClose: () => void`
- `partner === null` 처리: `<Modal isOpen={false} ...>` 빈 모달 반환 (hooks 호출 순서 보장)
- 섹션 구성: 헤더(즐겨찾기/상태/빠른액션) → 프로필 → 별칭+메모 인라인 편집 → 거래 통계 4타일 → 정기배송 목록 → 푸터(닫기)
- **인라인 편집 패턴**: 클릭 시 `editingNickname`/`editingNotes` state 토글 → `<input autoFocus>`/`<textarea autoFocus>` → `onBlur`/`Enter`로 `useUpdatePartner.mutate({ id, data: { nickname/notes } })`. 미변경 시 mutate 스킵. Esc로 취소.
- **정기배송 목록 패턴**: 펼침/접힘 토글 (`expandedSubId` state). 펼친 영역에 시작/종료일, 배송지, 메모, 항목 리스트, 액션 버튼(주문 생성/일시정지·재개/삭제) 노출.
- **selectedPartner 동기화**: 부모 페이지(seller/buyer partners)에서 `useEffect`로 partners 갱신 시 `selectedPartner`도 최신 row로 동기화 — 별칭/즐겨찾기 PATCH 후 모달이 stale 데이터 보여주지 않도록.

```typescript
// seller|buyer partners 페이지
useEffect(() => {
  if (!selectedPartner) return;
  const fresh = partners.find((p) => p.id === selectedPartner.id);
  if (fresh && fresh !== selectedPartner) setSelectedPartner(fresh);
  if (!fresh) setSelectedPartner(null);  // 삭제된 경우
}, [partners, selectedPartner]);
```

##### SubscriptionFormModal (`components/subscriptions/SubscriptionFormModal.tsx`)
- **Props**: `isOpen`, `onClose`, `partner: Partner`, `myRole: 'SELLER' | 'BUYER'`
- 주기(WEEKLY/BIWEEKLY/MONTHLY) → 요일 또는 결제일(1~31) → 시작일/종료일 → 납품 주소/메모 → 상품 라인 (다중)
- **상품 검색은 myRole에 따라 seller_id 분기**:
  ```typescript
  // SELLER가 만들 때: 본인(partner.user_id) 상품
  // BUYER가 만들 때:  거래처 판매자(partner.partner_user_id) 상품
  const sellerIdForProducts =
    myRole === 'SELLER' ? partner.user_id : partner.partner_user_id;
  useProducts({ seller_id: sellerIdForProducts, limit: 200 });
  ```
- **seller_id/buyer_id 매핑**:
  ```typescript
  const seller_id = myRole === 'SELLER' ? partner.user_id : partner.partner_user_id;
  const buyer_id  = myRole === 'BUYER'  ? partner.user_id : partner.partner_user_id;
  ```
- 검증: 모든 항목 product_id 선택, quantity ≥ 1, unit_price ≥ 0, start_date ≥ today, end_date ≥ start_date, MONTHLY는 day_of_month 1~31, WEEKLY/BIWEEKLY는 day_of_week 0~6
- 날짜는 timezone-safe 문자열 조합 — `defaultStartDate()`는 오늘+7일을 `YYYY-MM-DD` 로 직접 생성 (ISO 변환 금지)

##### NextDeliveryLabel — 정기배송 D-day 표시 (검증됨, 2026-04-29)

`components/subscriptions/NextDeliveryLabel.tsx` — 정기배송 "다음 배송일"을 D-day 카운트와 함께 강조 표시하는 공용 컴포넌트.

**Props 시그니처:**
```typescript
{
  date: string | null | undefined;          // 'YYYY-MM-DD'. null/undefined → "-"
  calendarHref?: string;                    // 있으면 <Link>, 없으면 <span>
  prefix?: string;                          // 기본 '다음 배송'. ''(빈 문자열) → 라벨 prefix 생략
  ariaLabel?: string;
  className?: string;
}
```

**사용처 4곳 (모두 동일 컴포넌트 재사용):**
- `app/(dashboard)/buyer/subscriptions/page.tsx` — 카드 요약 행, prefix 기본 사용, **calendarHref 미전달** (아래 nested DOM 가드 참조)
- `app/(dashboard)/seller/subscriptions/page.tsx` — 동일
- `app/(dashboard)/buyer/orders/page.tsx` — 정기배송 탭 DataTable 셀, `prefix=""` 로 헤더 중복 회피, calendarHref 전달 OK (셀이 단독 컬럼이라 nested 문제 없음)
- `app/(dashboard)/seller/orders/page.tsx` — 동일

**핵심 패턴:**
- 오늘 날짜는 KST 기준 — `getTodayKstString()` (`lib/date.ts`).
- D-day 계산은 `diffInDays(today, target)` (`lib/date.ts`) — `Date.UTC` 로 변환 후 86_400_000 으로 나눈다 (DST 영향 회피).
- `diff > 0` → "D-N" 회색 / `diff === 0` → "D-Day" 빨강+`AlertCircle` / `diff < 0` → "D+N 지남" 빨강+`AlertCircle`.
- `<Link onClick={(e) => e.stopPropagation()}>` 로 부모 카드의 행 펼침 onClick 과 분리 (DataTable 셀 등 부모가 클릭 핸들러를 가진 영역에서).
- `calendarHref` 는 role 별로 다르게: `/buyer/calendar?date=${date}` 또는 `/seller/calendar?date=${date}`.

**Nested interactive element 가드 (검증됨, 2026-04-29):**

부모가 `<button>` 인 영역(예: 정기배송 카드의 행 펼침 토글)에서는 **calendarHref 를 전달하지 않는다.** 전달하면 `<button>` 안에 `<a>` 가 들어가 HTML invalid → React `validateDOMNesting` 경고 + Safari/Firefox 가 button 종료를 강제로 고쳐 layout 이 깨질 위험. `e.stopPropagation()` 만으로 우회 불가 (DOM 구조 자체가 invalid).

**해결 패턴 — 정기배송 페이지의 카드 헤더:**
```tsx
// ❌ 카드 헤더 <button> 안에 calendarHref 전달 → <a> nested → invalid
<button onClick={toggleRow}>
  <NextDeliveryLabel date={...} calendarHref="/buyer/calendar?date=..." />
</button>

// ✅ 헤더에서는 <span> 으로만 렌더하고, 펼침 영역에 별도 버튼으로 분리
<button onClick={toggleRow}>
  <NextDeliveryLabel date={sub.next_delivery_date} />  {/* calendarHref 생략 */}
</button>
{isExpanded && (
  <div>
    {/* ... 다른 액션 버튼들 옆에 ... */}
    {sub.next_delivery_date && (
      <button onClick={() => router.push(`/buyer/calendar?date=${sub.next_delivery_date}`)}>
        <CalendarDays className="h-3.5 w-3.5" />
        캘린더에서 보기
      </button>
    )}
  </div>
)}
```

DataTable 셀처럼 부모가 `<button>` 이 아닌 컨텍스트에서는 calendarHref 를 그대로 전달해도 무방.

**`lib/date.ts` 신규 헬퍼:**
- `getTodayKstString(): string` — 'YYYY-MM-DD' (KST). 백엔드 날짜 컬럼과 직접 문자열 비교 가능. `TodayTasksWidget.tsx` 에 있던 사설 헬퍼를 공용으로 승격.
- `diffInDays(base, target): number` — 'YYYY-MM-DD' 두 문자열 간 일수 차. 잘못된 입력은 0 반환.

##### 캘린더 페이지 ?date= 쿼리 진입 (검증됨, 2026-04-29)

`app/(dashboard)/buyer/calendar/page.tsx` 와 `seller/calendar/page.tsx` 는 `?date=YYYY-MM-DD` 쿼리를 받으면 해당 월/일로 즉시 이동한다 (`NextDeliveryLabel` 클릭 시 사용).

**Suspense boundary 필수 (Next.js 14 App Router):**
`useSearchParams()` 를 client page root 에서 직접 사용하면 빌드 경고 + 페이지 전체가 동적 fallback 으로 강제된다. 실제 로직은 `BuyerCalendarPageInner` / `SellerCalendarPageInner` 에 두고 default export 는 얇은 `<Suspense>` wrapper:

```tsx
'use client';
import { Suspense, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';

function BuyerCalendarPageInner() {
  const searchParams = useSearchParams();
  // ... 모든 페이지 로직
}

export default function BuyerCalendarPage() {
  return (
    <Suspense fallback={<div className="py-12 text-center text-sm text-gray-400">캘린더 로딩 중...</div>}>
      <BuyerCalendarPageInner />
    </Suspense>
  );
}
```

같은 패턴은 `useSearchParams` 를 사용하는 모든 client page 에 적용한다 (현재 buyer/seller calendar 두 곳, buyer/browse 도 향후 동일하게 wrap 권장).

```tsx
const searchParams = useSearchParams();
const dateParam = searchParams?.get('date') ?? null;
const parsedQuery = useMemo(() => {
  if (!dateParam) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateParam);
  if (!m) return null;
  // ... validate & return { year, month, day, dateStr }
}, [dateParam]);

// 초기 state 를 쿼리 기반으로 설정
const [year, setYear] = useState(parsedQuery?.year ?? today.getFullYear());
const [month, setMonth] = useState(parsedQuery?.month ?? today.getMonth() + 1);
const [selectedDate, setSelectedDate] = useState<string | null>(parsedQuery?.dateStr ?? null);
const [dayModalDate, setDayModalDate] = useState<string | null>(parsedQuery?.dateStr ?? null);

// 같은 페이지에서 쿼리만 변경되는 클라이언트 네비게이션 동기화
useEffect(() => {
  if (!parsedQuery) return;
  setYear(parsedQuery.year);
  setMonth(parsedQuery.month);
  setSelectedDate(parsedQuery.dateStr);
  setDayModalDate(parsedQuery.dateStr);
}, [parsedQuery]);
```

쿼리 형식이 잘못되면 무시하고 오늘 기준으로 폴백 (안전 기본값).

##### EventType 'SUBSCRIPTION' + subscription_id 동기 일정 (검증됨, 2026-04-28)
`types/calendar.ts`의 `EventType` union 에 `'SUBSCRIPTION'` 포함, `CalendarEvent` 인터페이스에 `subscription_id: string | null` 필드 포함.

정기배송 일정은 두 경로로 들어온다:
- **백엔드 동기 일정** — 정기배송 ACTIVE 시 백엔드가 양 당사자 캘린더에 INSERT. `event_type = 'SHIPMENT'`(판매자) / `'DELIVERY'`(구매자), `subscription_id != null`, `order_id = null`
- **프론트 가상 이벤트** — `useSubscriptions({ status: 'ACTIVE' })` 로부터 향후 3개월(약 12회) 분량 합성. `event_type = 'SUBSCRIPTION'`, id prefix `sub-virtual-`, `subscription_id = sub.id`

**중요 — Dedupe 필수 (검증됨, 2026-04-28)**: 두 경로가 동시에 존재하므로 같은 `(subscription_id, event_date)` 가 백엔드 응답에 이미 있으면 가상 이벤트 합성을 skip 해야 셀/리스트에 정기배송이 두 번 노출되지 않는다. 백엔드 backfill 안 된 기존 ACTIVE 정기배송에 대해서는 가상 이벤트 fallback 을 유지하여 점진적 전환을 보장한다.

```typescript
// seller|buyer/calendar/page.tsx — 가상 이벤트 합성 + dedupe
// 백엔드가 이미 INSERT 한 (subscription_id, event_date) Set 만들기
const backendSubKeys = useMemo(() => {
  const keys = new Set<string>();
  for (const ev of [...baseMonthEvents, ...baseAllEvents]) {
    if (ev.subscription_id) keys.add(`${ev.subscription_id}|${ev.event_date}`);
  }
  return keys;
}, [baseMonthEvents, baseAllEvents]);

const subscriptionVirtualEvents: CalendarEvent[] = useMemo(() => {
  const events: CalendarEvent[] = [];
  for (const sub of activeSubs) {
    let cur = new Date(sub.next_delivery_date);
    let round = 1;
    while (cur <= horizon && round <= 50) {
      const dateStr = `${cur.getFullYear()}-${String(cur.getMonth()+1).padStart(2,'0')}-${String(cur.getDate()).padStart(2,'0')}`;
      // Dedupe — 백엔드 동기 INSERT 된 (subscription_id, date) 면 가상 이벤트 skip
      if (!backendSubKeys.has(`${sub.id}|${dateStr}`)) {
        events.push({
          id: `sub-virtual-${sub.id}-${round}`,
          user_id: '', order_id: null,
          subscription_id: sub.id,  // ← 동기 일정과 일관된 식별자, color/label 분기 트리거
          title: '정기배송 예정',
          event_type: 'SUBSCRIPTION',
          // ...나머지 필드
        });
      }
      // 다음 회차 계산 — 백엔드 compute_next_date 와 동일 로직 (생략)
      round += 1;
    }
  }
  return events;
}, [activeSubs, backendSubKeys]);
```

##### 정기배송 일정 색상/라벨 — subscription_id 우선 (필수 패턴)
`constants/status.ts`의 `getCalendarEventColorClass` / `getCalendarEventLabel` 은 **`subscription_id` 가 가장 먼저** 분기된다. 백엔드 동기 일정은 `event_type` 이 `SHIPMENT`/`DELIVERY` 라 일반 출하/입고와 색이 같아져 정기배송을 구분할 수 없기 때문이다.

```typescript
// constants/status.ts
export function getCalendarEventColorClass(event) {
  if (event.subscription_id) return EVENT_TYPE_COLOR_CLASS.SUBSCRIPTION; // bg-purple-500
  if (event.order_status && event.order_status in ORDER_STATUS_CONFIG) {
    return ORDER_STATUS_CONFIG[event.order_status].solidClassName;
  }
  return EVENT_TYPE_COLOR_CLASS[event.event_type] ?? EVENT_TYPE_COLOR_CLASS.OTHER;
}

export function getCalendarEventLabel(event) {
  if (event.subscription_id) return EVENT_TYPE_LABEL.SUBSCRIPTION; // '정기배송'
  if (event.order_status && event.order_status in ORDER_STATUS_CONFIG) {
    return ORDER_STATUS_CONFIG[event.order_status].label;
  }
  return EVENT_TYPE_LABEL[event.event_type] ?? '기타';
}
```

`EVENT_TYPE_COLOR_CLASS.SUBSCRIPTION = 'bg-purple-500'` / `EVENT_TYPE_LABEL.SUBSCRIPTION = '정기배송'`. 다른 화면(주문 페이지 정기배송 출처 뱃지)의 `bg-purple-100/text-purple-700` 톤과 통일.

##### 정기배송 시각적 식별 — Repeat 아이콘 + 보라 뱃지
모든 캘린더 진입 지점에서 `subscription_id` 존재 시 lucide `Repeat` 아이콘과 `bg-purple-100 text-purple-700` 뱃지로 일관 표시:

| 위치 | 시각 표시 |
|------|---------|
| 그리드 셀 일정 칩 | `<Repeat className="h-2.5 w-2.5" />` + main 텍스트 (셀 안 좁음) |
| 우측 "전체 일정" 리스트 카드 | 색상 점 → `<Repeat className="h-3 w-3 text-purple-600" />` → 제목 + 우측에 보라 라벨(`정기배송`) |
| `DayEventsModal` 카드 | 카드 자체 `border-purple-200 bg-purple-50/30` + Repeat 아이콘 + 보라 라벨 |
| `EventDetailModal` 헤더 | 제목 옆 `<Repeat className="h-4 w-4 text-purple-600" />` |
| `EventDetailModal` 메타 영역 | `정기배송` 보라 pill + Repeat 아이콘 |

```tsx
// 패턴 — 어느 위치든 동일
const isSubscription = !!ev.subscription_id;  // 가상 이벤트도 subscription_id 채워졌으므로 동일 분기
{isSubscription && <Repeat className="h-3 w-3 text-purple-600" />}
<span className={cn('rounded-full px-2 py-0.5 text-[10px]',
  isSubscription ? 'bg-purple-100 text-purple-700' : 'bg-gray-100 text-gray-600'
)}>{typeLabel}</span>
```

##### EventDetailModal — 정기배송 일정 → "정기배송 관리로 이동" 링크
`subscription_id` 가 있는 일정 또는 가상 SUBSCRIPTION 이벤트는 모달 본문 하단에 보라 톤 링크 버튼 노출. 클릭 시 역할별 주문 페이지의 `subscription` 탭으로 이동.

```tsx
const isSubscription = !!event.subscription_id || event.event_type === 'SUBSCRIPTION';

const handleOpenSubscription = () => {
  router.push(role === 'buyer' ? '/buyer/orders?tab=subscription' : '/seller/orders?tab=subscription');
};

{isSubscription && (
  <button onClick={handleOpenSubscription}
    className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg border border-purple-200 bg-purple-50 px-4 py-2 text-sm font-medium text-purple-700 hover:bg-purple-100">
    <ExternalLink className="h-4 w-4" /> 정기배송 관리로 이동
  </button>
)}
```

`order_id` 가 있는 일정에는 기존 "주문 상세 보기" 버튼 그대로 유지 — 정기배송 일정은 `order_id == null` 이므로 두 버튼이 동시에 뜨지 않는다.

##### EventDetailModal — 가상 이벤트 삭제 버튼 숨김 (함정 유지)
`event.id`가 `'sub-virtual-'` 로 시작하거나 `event_type === 'SUBSCRIPTION'` 인 경우 DB row가 없으므로 `useDeleteCalendarEvent.mutate(event.id)`가 404를 던진다. 푸터의 삭제 버튼을 조건부로 숨겨야 한다. (백엔드 동기 정기배송 일정은 DB row 가 있으므로 삭제 가능 — 가상 이벤트만 차단)

```tsx
const isVirtual = event.event_type === 'SUBSCRIPTION' || event.id.startsWith('sub-virtual-');

footer={
  <>
    {!isVirtual && <button onClick={handleDelete}>...삭제...</button>}
    <button onClick={onClose}>닫기</button>
  </>
}
```

`EVENT_TYPE_OPTIONS` (일정 추가 모달의 select) 에는 `SUBSCRIPTION` 추가하지 **않음** — 사용자가 수동 등록할 수 없는 시스템 타입.

##### 정기배송 출처 뱃지 — 주문/견적 페이지
`Order.subscription_id`가 있으면 상품 컬럼에 보라색 pill `정기 N회차`(N = `subscription_round`) 표시. 상세 슬라이드 헤더에도 같은 뱃지를 주문번호 아래에 노출.

```tsx
{item.subscription_id && (
  <span className="inline-flex flex-shrink-0 items-center rounded-full bg-purple-100 px-1.5 py-0.5 text-[10px] font-medium text-purple-700">
    정기 {item.subscription_round ?? '?'}회차
  </span>
)}
```

##### 빠른 액션 라우팅 매트릭스 (V1.5 갱신)

| 위치 | 채팅 시작 | 주문 작성 |
|------|---------|---------|
| seller/partners 행 | (모달 안 버튼) `/seller/chat?room_id=${id}` | **숨김** (V1.5도 미존재) |
| buyer/partners 행 | (모달 안 버튼) `/buyer/chat?room_id=${id}` | (모달 안 버튼) `/buyer/browse?seller_id=${id}` |
| 거래처 행 자체 | 클릭 시 `PartnerDetailModal` 오픈 | — |

#### 거래처 V1.5 Phase 3 — 즐겨찾기 필터 + 삭제 (검증됨, 2026-04-27)

##### 즐겨찾기만 토글 — 클라이언트 필터링 (백엔드 미지원 함정)

백엔드 `partner_service.list_partners` 는 현재 `is_favorite` 파라미터를 받지 않는다. `?is_favorite=true` 를 쿼리에 추가해도 무시되므로 **클라이언트 사이드에서 필터링**한다 (V1.6 정도에 백엔드 지원 추가 가능).

```tsx
// seller|buyer/partners/page.tsx
const [favoriteOnly, setFavoriteOnly] = useState(false);

// 정렬은 항상 동일 — is_favorite desc → created_at desc
const sortedPartners = useMemo(
  () => [...partners].sort((a, b) => {
    if (a.is_favorite !== b.is_favorite) return a.is_favorite ? -1 : 1;
    return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
  }),
  [partners]
);

// favoriteOnly === true 인 경우만 필터 적용
const visiblePartners = useMemo(
  () => favoriteOnly ? sortedPartners.filter((p) => p.is_favorite) : sortedPartners,
  [sortedPartners, favoriteOnly]
);
```

토글 버튼 스타일 — 활성/비활성 색상 명세:
```tsx
className={`mb-4 inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm font-medium transition-colors ${
  favoriteOnly
    ? 'border-yellow-300 bg-yellow-50 text-yellow-600'
    : 'border-gray-200 bg-white text-gray-500 hover:bg-gray-50'
}`}
```

`SearchFilterBar` 가 자체 `mb-4` 를 갖고 있어 토글 버튼도 동일 `mb-4` 를 줘야 baseline 정렬이 맞는다. 컨테이너는 `flex flex-wrap items-center gap-3` + 검색 박스에 `flex-1 min-w-[240px]` 을 주어 좁은 화면에서 토글이 다음 줄로 떨어지도록.

##### 거래처 삭제 — 활성 정기배송 PAUSED 일괄 처리 후 soft-delete

거래처 soft-delete 시 연결된 활성 정기배송이 그대로 남아 다음 회차에 주문이 자동 생성되면 안 된다. **삭제 전에 그 거래처와 연결된 ACTIVE 정기배송을 모두 PAUSED 로 전환** (데이터 보존 위해 정기배송 자체는 삭제하지 않음).

```typescript
// seller|buyer/partners/page.tsx
const subData = useSubscriptions({ status: 'ACTIVE', limit: 200 });
const updateSubscription = useUpdateSubscriptionGeneric();
const deletePartner = useDeletePartner();

const handleDeletePartner = async (partner: Partner) => {
  if (deletePendingId) return;
  const confirmed = window.confirm(
    `'${partner.nickname || partner.partner_company || partner.partner_name || ''}' 거래처를 삭제하시겠습니까?\n진행 중인 정기배송이 일시정지됩니다.`
  );
  if (!confirmed) return;

  setDeletePendingId(partner.id);
  try {
    // 1) Subscription.partner_id 로 매칭 (partner_user_id 가 아님 — 함정)
    const activeSubs = (subData.data?.data ?? []).filter(
      (s) => s.partner_id === partner.id && s.status === 'ACTIVE'
    );
    await Promise.all(
      activeSubs.map((s) =>
        updateSubscription.mutateAsync({ id: s.id, data: { status: 'PAUSED' } })
      )
    );
    await deletePartner.mutateAsync(partner.id);
    setSelectedPartner(null);  // 모달 열려있으면 닫기
  } catch (e) {
    console.error('[seller/partners] delete failed:', e);
    alert('삭제에 실패했습니다. 잠시 후 다시 시도해주세요.');
  } finally {
    setDeletePendingId(null);
  }
};
```

##### useUpdateSubscriptionGeneric — 동적 id 일괄 처리용 훅 (검증됨)

기존 `useUpdateSubscription(id)` 는 컴포넌트 마운트 시점에 id 가 고정되어야 하므로 `Promise.all` 로 여러 정기배송을 한꺼번에 update 할 수 없다. 이 한계 때문에 `hooks/useSubscriptions.ts` 에 일반화된 변형을 추가:

```typescript
export function useUpdateSubscriptionGeneric() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: SubscriptionUpdate }) =>
      api.patch<SuccessResponse<Subscription>>(`/subscriptions/${id}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['subscriptions'] });
      qc.invalidateQueries({ queryKey: ['partner-stats'] });
    },
  });
}
```

`mutateAsync({ id, data })` 형태로 호출 → 거래처 삭제 시 활성 정기배송 일괄 PAUSED 같은 시나리오에 사용. 단건 update 는 기존 `useUpdateSubscription(id)` 그대로 유지.

##### 삭제 UI — 행 액션 + 모달 양쪽

거래처 행 액션 영역 (DataTable column) + `PartnerDetailModal` 헤더 빠른액션 영역 양쪽에 삭제 버튼 노출. 핸들러는 페이지 컨테이너에 한 번만 정의하고 모달에는 props 로 위임 (`onDelete?: (partner: Partner) => void`, `deletePending?: boolean`).

```tsx
// 행 액션 — 작은 빨간 hover Trash2 아이콘만
<button
  onClick={(e) => { e.stopPropagation(); handleDeletePartner(item); }}
  disabled={deletePendingId === item.id || !!deletePendingId}
  className="inline-flex items-center justify-center rounded-lg border border-gray-200 bg-white p-1.5 text-gray-400 hover:border-red-300 hover:bg-red-50 hover:text-red-600 disabled:opacity-50"
>
  <Trash2 className="h-3.5 w-3.5" />
</button>

// 모달 헤더 — 라벨 포함 빨간 outline 버튼
{onDelete && (
  <button
    onClick={() => onDelete(partner)}
    disabled={deletePending}
    className="inline-flex items-center gap-1 rounded-lg border border-red-300 bg-white px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
  >
    <Trash2 className="h-3.5 w-3.5" />
    거래처 삭제
  </button>
)}
```

`onDelete` 가 없으면 모달에 삭제 버튼이 노출되지 않음 — 호출처(거래처 페이지)에서만 삭제 가능. 다른 컨텍스트에서 모달이 재사용될 때 안전하게 동작.

##### 확인 다이얼로그 — `window.confirm` (공통 ConfirmDialog 부재)

`components/common/` 에 ConfirmDialog 가 없으므로 (Modal/AuthGuard/CancelOrderModal 등만 존재) `window.confirm` 으로 처리. 메시지에 `\n` 으로 줄바꿈 포함.

##### byte-identical 유지 규칙

seller/buyer 양쪽 page.tsx 의 차이는 다음으로만 한정 (diff 검증):
- 컴포넌트명 (`SellerPartnersPage` vs `BuyerPartnersPage`)
- 채팅 라우트 (`/seller/chat` vs `/buyer/chat`)
- 주문 작성 라우트 (`/seller/orders/new?buyer_id=` vs `/buyer/browse?seller_id=`)
- 최근 거래 컬럼 라우트 (`/seller/orders?partner_user_id=` vs `/buyer/orders?partner_user_id=`)
- `showCreateOrderAction` (false vs true)
- log prefix (`[seller/partners]` vs `[buyer/partners]`)
- copy (`바이어 거래처` vs `공급처`, 검색 placeholder)
- `myRole` ('SELLER' vs 'BUYER')

즐겨찾기 토글, 삭제 핸들러, useMemo 정렬 로직 등은 양쪽 완전히 동일.

##### 최근 거래 컬럼 (PM Report #8 작업 5)

`partners` 응답에 `last_trade_date` (ISO 'YYYY-MM-DD'), `last_trade_amount` (KRW int) 두 옵션 필드가 포함됨. 거래 없으면 둘 다 null.

거래처 목록 컬럼 순서: `즐겨찾기 / 업체명 / 유형 / 등록일 / 최근 거래 / 상태 / 액션`. 컬럼 위치는 등록일과 상태 사이.

```tsx
{
  key: 'last_trade',
  header: '최근 거래',
  render: (item) => {
    // PENDING_OUTGOING/INCOMING 은 거래가 있을 수 없으므로 항상 '아직 거래 없음'
    const isPreTrade =
      item.status === 'PENDING_OUTGOING' || item.status === 'PENDING_INCOMING';
    const hasTrade =
      !isPreTrade && item.last_trade_date != null && item.last_trade_amount != null;

    if (!hasTrade) return <span className="text-sm text-gray-400">아직 거래 없음</span>;

    return (
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation(); // 행 onClick(상세 모달) 차단
          router.push(`/seller/orders?partner_user_id=${item.partner_user_id}`);
        }}
        className="text-left text-sm text-gray-700 hover:text-primary-700 hover:underline"
      >
        {formatDate(item.last_trade_date as string)}
        {' · '}
        {(item.last_trade_amount as number).toLocaleString('ko-KR')}원
      </button>
    );
  },
},
```

- 날짜 포맷은 기존 등록일과 동일하게 `formatDate` 재사용 (ko-KR 'YYYY. MM. DD.').
- 금액 포맷은 `.toLocaleString('ko-KR')` + '원' (천단위 콤마).
- 행 onClick 이 거래처 상세 모달을 열기 때문에 셀 내부 버튼은 반드시 `e.stopPropagation()` 호출.
- `PENDING_OUTGOING` 행은 다른 컬럼들과 동일하게 `opacity-60` 적용.

---

#### V1.6 — 거래처/정기배송 양방향 승인 UI (검증됨, 2026-04-27)

##### 거래처 PartnerStatus 확장

`PartnerStatus` union 에 `PENDING_OUTGOING` / `PENDING_INCOMING` 추가. `PENDING` 은 V1.5 이전 데이터 호환용으로 deprecated 상태로 유지.

```typescript
// types/partner.ts
export type PartnerStatus =
  | 'ACTIVE'
  | 'INACTIVE'
  | 'PENDING'              // deprecated — 호환만
  | 'PENDING_OUTGOING'     // 본인이 보낸 요청
  | 'PENDING_INCOMING';    // 받은 요청
```

`PARTNER_STATUS_CONFIG` 의 신규 라벨 컬러:
- `PENDING_OUTGOING`: `bg-yellow-100 text-yellow-800` 라벨 "보낸 요청"
- `PENDING_INCOMING`: `bg-blue-100 text-blue-800` 라벨 "받은 요청"

##### usePartnerStatusMap — 회원 검색 카드 분기용 (Set → Map)

기존 `usePartnerUserIdSet()` 은 "이미 거래처인가" 까지만 알 수 있었으나, 4종 분기 UI 가 필요해져 `Map<partner_user_id, PartnerStatus>` 로 확장.

```typescript
// hooks/usePartners.ts
export function usePartnerStatusMap(): Map<string, PartnerStatus> {
  const { data } = usePartners();   // status 인자 없이 호출 → 백엔드 list_partners 가 모든 상태 반환
  return useMemo(() => {
    const m = new Map<string, PartnerStatus>();
    for (const p of data?.data ?? []) m.set(p.partner_user_id, p.status);
    return m;
  }, [data]);
}
```

**백엔드 list_partners 동작 확인**: `partner_service.list_partners` 는 `status` 인자 미전송 시 `if status: query = query.eq("status", status)` 분기를 타지 않아 모든 상태(ACTIVE/INACTIVE/PENDING_*)를 반환. 별도 백엔드 수정 불필요.

기존 `usePartnerUserIdSet()` 은 호환 유지(AddPartnerModal 등 사용). 새로운 분기 UI 는 `usePartnerStatusMap()` + `partnerIdByUserId` Map 조합으로 처리.

##### 회원 검색 카드 — 4종 분기 UI

```tsx
{/* ACTIVE / PENDING (deprecated) → 거래처 등록됨 (회색, Check 아이콘) */}
{(partnerStatus === 'ACTIVE' || partnerStatus === 'PENDING') && (
  <span className="bg-gray-100 text-gray-500">거래처 등록됨</span>
)}
{/* PENDING_OUTGOING → 보낸 요청 (노란색, Clock 아이콘, 비활성) */}
{partnerStatus === 'PENDING_OUTGOING' && (
  <span className="bg-yellow-50 border border-yellow-200 text-yellow-700">요청 보냄</span>
)}
{/* PENDING_INCOMING → 수락 버튼 (파란색, Inbox 아이콘) */}
{partnerStatus === 'PENDING_INCOMING' && partnerId && (
  <button onClick={() => onAcceptPartner(partnerId)} className="bg-blue-600 text-white">
    요청 받음 — 수락
  </button>
)}
{/* (없음) 또는 INACTIVE → 거래처 추가 (primary outline, UserPlus 아이콘) */}
```

PENDING_INCOMING 카드의 수락 버튼은 회원 user_id 가 아닌 **partner row id** 를 사용한다 — `useAcceptPartner.mutate(partnerId)`. 회원 카드 컴포넌트에서는 `partnerIdByUserId.get(member.id)` 로 partner.id 매핑.

##### 거래처 페이지 상단 — 받은 요청 섹션 + 메인 리스트 통합 (PENDING_OUTGOING 비대칭 버그 수정, 2026-04-28)

```tsx
// PENDING_INCOMING 만 별도 섹션 (수락/거절 액션 필요 → 분리 UI 정당)
const incomingRequests = partners.filter((p) => p.status === 'PENDING_INCOMING');
// PENDING_OUTGOING 은 메인 리스트에 통합 — 본인이 보낸 요청도 자기 거래처 화면에 보이도록
const mainListPartners = partners.filter(
  (p) =>
    p.status === 'ACTIVE' ||
    p.status === 'INACTIVE' ||
    p.status === 'PENDING' ||           // deprecated 호환
    p.status === 'PENDING_OUTGOING'     // 본인이 보낸 요청도 메인 노출
);
```

**버그 배경**: 이전 구조에선 `PENDING_OUTGOING` row 가 메인 리스트에서 제외되고 "보낸 요청" 별도 섹션에만 표시됐다. 그런데 동일한 거래 관계의 반대편(PENDING_INCOMING) 사용자에겐 "받은 요청" 섹션에 정상 노출 → 본인 메인 거래처 리스트에서 자기 보낸 요청을 못 찾는 비대칭이 발생. **수정**: PENDING_OUTGOING 을 메인 테이블에 통합 + 시각적 구분(opacity-60 + "승인 대기 중" 안내) + 빠른 액션(채팅/주문) 비활성. "보낸 요청" 별도 섹션은 제거.

- 받은 요청 섹션: `bg-blue-50 border border-blue-200 rounded-xl`. 각 행에 [수락] [거절] 버튼.
- 메인 테이블의 PENDING_OUTGOING row:
  - 업체명 셀에 `opacity-60` 적용, 부가 텍스트로 `· 승인 대기 중` (text-yellow-700) 노출
  - StatusBadge 는 그대로 PARTNER_STATUS_CONFIG 의 "보낸 요청" (yellow) 뱃지 표시
  - 즐겨찾기 토글 / 채팅 버튼 / 주문 작성 버튼 모두 `disabled + cursor-not-allowed opacity-40` (아직 거래처가 아니므로)
  - 삭제 버튼은 활성 (라벨/툴팁만 "요청 회수" 로 변경, `aria-label` 도 동일)
  - `handleDeletePartner` 가 status 검사해서 confirm 메시지를 다르게: `'X' 에게 보낸 거래처 요청을 회수하시겠습니까?` vs `'X' 거래처를 삭제하시겠습니까?\n진행 중인 정기배송이 일시정지됩니다.`
- 행 클릭 → PartnerDetailModal 진입 가능. 모달 안에서도 동일한 잠금 처리.

##### PartnerDetailModal — PENDING_OUTGOING 잠금 처리

```tsx
const isPendingOutgoing = partner.status === 'PENDING_OUTGOING';

// 헤더의 즐겨찾기 / 채팅 시작 / 주문 작성 모두 disabled + opacity-40
// 거래처 삭제 버튼은 활성, 라벨만 "요청 회수" 로
{isPendingOutgoing ? '요청 회수' : '거래처 삭제'}

// 안내 띠 (헤더 바로 아래)
{isPendingOutgoing && (
  <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-3 text-yellow-800">
    <Clock /> 보낸 거래처 요청이 수락되기 전까지 ... 거래 액션을 사용할 수 없습니다.
  </div>
)}

// 정기배송 관련 섹션은 전부 isPendingOutgoing 일 때 숨김
{!isPendingOutgoing && incomingPendingSubs.length > 0 && (...)}
{!isPendingOutgoing && outgoingPendingSubs.length > 0 && (...)}
{!isPendingOutgoing && (<section>정기배송 ({sortedSubs.length})</section>)}
```

`useAcceptPartner` / `useRejectPartner` 훅은 mutation 성공 시 `['partners']` 만 invalidate. accept 는 양쪽 row 가 ACTIVE 로 전환되므로 자동으로 메인 리스트에서 PENDING_OUTGOING → ACTIVE 로 자연 전환된다(opacity-60 / 잠금 해제 자동 적용).

##### 정기배송 SubscriptionStatus 확장

```typescript
// types/subscription.ts
export type SubscriptionStatus =
  | 'PENDING'    // V1.6 신규 — 생성 직후 상대 수락 대기
  | 'ACTIVE'
  | 'PAUSED'
  | 'ENDED'
  | 'CANCELLED'
  | 'REJECTED';  // V1.6 신규 — 상대가 거절

export interface Subscription {
  // ...기존
  created_by: string | null;  // V1.6 — 정기배송을 만든 사용자 (수락 권한 판단용)
}
```

##### SUBSCRIPTION_STATUS_CONFIG — 신규 통합 색 매핑

`constants/status.ts` 에 추가:

```typescript
export const SUBSCRIPTION_STATUS_CONFIG = {
  PENDING:   { label: '승인 대기', className: 'bg-amber-100 text-amber-800',   solidClassName: 'bg-amber-500' },
  ACTIVE:    { label: '진행중',    className: 'bg-purple-100 text-purple-800', solidClassName: 'bg-purple-500' },
  PAUSED:    { label: '일시정지',  className: 'bg-gray-100 text-gray-700',     solidClassName: 'bg-gray-500' },
  ENDED:     { label: '종료',      className: 'bg-slate-100 text-slate-700',   solidClassName: 'bg-slate-500' },
  CANCELLED: { label: '취소',      className: 'bg-red-100 text-red-700',       solidClassName: 'bg-red-500' },
  REJECTED:  { label: '거절',      className: 'bg-rose-100 text-rose-700',     solidClassName: 'bg-rose-500' },
} as const satisfies Record<SubscriptionStatus, SubscriptionStatusConfig>;
```

캘린더 가상 이벤트 색은 `EVENT_TYPE_COLOR_CLASS.SUBSCRIPTION` 도 `bg-purple-500` 으로 통일 — ACTIVE 정기배송 색과 일치(과거 `bg-purple-400` 은 약해 보였음).

##### PartnerDetailModal — 정기배송 분류 (받은 요청 / 보낸 요청 / 메인)

```typescript
import { useAuthStore } from '@/store/authStore';
const { user } = useAuthStore();
const currentUserId = user?.id ?? '';

// 받은 요청: PENDING + created_by != currentUser (NULL 아닐 때만)
const incomingPendingSubs = subscriptions.filter(
  (s) => s.status === 'PENDING' && s.created_by !== null && s.created_by !== currentUserId
);
// 보낸 요청: PENDING + created_by == currentUser (또는 NULL — V1.5 이전 데이터)
const outgoingPendingSubs = subscriptions.filter(
  (s) => s.status === 'PENDING' && (s.created_by === null || s.created_by === currentUserId)
);
// 메인: PENDING 외 모든 상태
const mainListSubs = subscriptions.filter((s) => s.status !== 'PENDING');
```

훅: `useAcceptSubscription` / `useRejectSubscription`. Accept 시 `['subscriptions', 'partner-stats', 'calendar']` 모두 invalidate — ACTIVE 전환 후 캘린더 가상 이벤트가 즉시 등장하도록.

##### 주문/견적 페이지 — "정기배송" 탭 (TabDef + isSubTab 분기)

```typescript
interface TabDef {
  key: string;
  label: string;
  statuses?: OrderStatus[];     // 일반 주문 탭
  isSubscription?: boolean;     // 정기배송 탭이면 true
}

const tabs: TabDef[] = [
  { key: 'pending', label: '견적/진행', statuses: [...] },
  { key: 'shipping', label: '배송중', statuses: ['SHIPPING'] },
  { key: 'done', label: '완료/취소', statuses: ['COMPLETED', 'CANCELLED'] },
  { key: 'subscription', label: '정기배송', isSubscription: true },   // 신규
];

const activeTabDef = tabs.find((t) => t.key === activeTab);
const isSubTab = !!activeTabDef?.isSubscription;
```

데이터 fetch 분기:
```typescript
// 일반 주문 — 정기배송 탭이면 status_in: [] 로 비활성화 (useOrders 가 자동 enabled: false)
const { data: listData } = useOrders({ status_in: isSubTab ? [] : activeStatuses, limit: 2000 });
// 정기배송 — 비활성 탭에서는 enabled: false
const subsData = useSubscriptions({ limit: 2000 }, { enabled: isSubTab });
```

`useOrders(filters, options?)` / `useSubscriptions(filters, options?)` 모두 `{ enabled?: boolean }` 옵션 추가. `useOrders` 는 추가로 `status_in: []` 을 자동 비활성화 가드(빈 status 배열로 모든 주문이 fetch 되는 사고 방지).

행 컬럼/액션:
- 컬럼: 상품, 상대방(seller_name 또는 buyer_name), 주기 라벨(매주/격주/매월), 다음 배송일, 회당 금액, 상태 뱃지(`SUBSCRIPTION_STATUS_CONFIG`), 액션
- 액션 분기:
  - PENDING + 본인 created_by 아님 → [수락] [거절] 버튼 (`onClick` 에 `e.stopPropagation()` 필수 — 행 클릭 핸들러와 분리)
  - ACTIVE → [회차 생성] 버튼 (window.confirm 후 useGenerateSubscriptionOrder)
  - 그 외 → 액션 없음
- 행 클릭 → 거래처 user_id 매핑 후 `PartnerDetailModal` 오픈 (selectedPartner 상태 사용)

```typescript
const handleSubRowClick = (sub: Subscription) => {
  const counterpartUserId = sub.seller_id === currentUserId ? sub.buyer_id : sub.seller_id;
  const partner = partners.find((p) => p.partner_user_id === counterpartUserId);
  if (partner) setSelectedPartner(partner);
  else alert('이 정기배송에 연결된 거래처가 없습니다.');
};
```

##### 주문 행 정기배송 출처 뱃지 — 색 통일

기존 `bg-purple-100 text-purple-700` (옅은 보라 + 보라 텍스트) → `bg-purple-500 text-white` 로 통일하여 정기배송 도메인 색(진한 보라)과 일치.

```tsx
{item.subscription_id && (
  <span className="inline-flex flex-shrink-0 items-center rounded-full bg-purple-500 px-1.5 py-0.5 text-[10px] font-medium text-white">
    정기 {item.subscription_round ?? '?'}회차
  </span>
)}
```

상세 슬라이드 헤더의 뱃지도 동일하게 `bg-purple-500 text-white` 로 변경.

##### useOrders / useSubscriptions — enabled 옵션 패턴 (검증됨)

탭 전환 시 비활성 탭의 fetch 를 차단하기 위한 패턴:

```typescript
// hooks/useOrders.ts
export function useOrders(filters?: OrderFilters, options?: { enabled?: boolean }) {
  const isEmptyStatusIn = filters?.status_in !== undefined && filters.status_in.length === 0;
  const enabled = (options?.enabled ?? true) && !isEmptyStatusIn;
  return useQuery({ queryKey: ['orders', filters], queryFn: ..., enabled });
}
```

`status_in: []` 가 자동으로 enabled=false 를 트리거하므로, 호출처에서는 `useOrders({ status_in: isSubTab ? [] : statuses })` 만 써도 안전. `useSubscriptions` 는 `enabled` 옵션만 명시적으로 전달.

##### byte-identical 유지 — 정기배송 탭 추가 후 (V1.6)

seller/buyer 양쪽 orders/page.tsx 차이는 기존과 동일하게 한정:
- 컴포넌트명 / 페이지 description / role-specific 컬럼명 (구매자 vs 판매자) / 채팅 라우트 / `myRole` ('SELLER' vs 'BUYER')
- 정기배송 탭 컬럼은 양쪽이 거의 동일하지만 "구매자" vs "판매자" 라벨과 buyer_name/seller_name 필드만 다름
- 액션 동작(수락/거절/회차 생성)은 양쪽 동일

---

#### 정기배송 전용 페이지 (`/{role}/subscriptions`) (검증됨, 2026-04-28)

V1.6 이전엔 정기배송 마스터 자체 관리는 `PartnerDetailModal` 에서만 가능했고, 주문/견적 페이지의 "정기배송" 탭은 보조 진입점일 뿐이었다. 사용자가 정기배송을 한눈에 보고 관리할 페이지가 없어 신규 추가:
- `frontend/app/(dashboard)/seller/subscriptions/page.tsx`
- `frontend/app/(dashboard)/buyer/subscriptions/page.tsx`

##### 사이드바 메뉴 추가 (`constants/menus.ts`)

거래처 다음 위치에 추가 (거래처 → 정기배송 흐름이 자연스러움):
```ts
{ label: '정기배송', href: '/{role}/subscriptions', icon: Repeat },
```
아이콘은 `lucide-react` 의 `Repeat` 사용 — `RefreshCw` 보다 "반복 일정" 의미에 적합.

##### 페이지 구조 — 카드 펼침 패턴 (Modal 대체)

별도 SubscriptionDetailModal 이 아직 없어 인라인 펼침으로 구현. DataTable 대신 카드 리스트로 작성:
```tsx
const [expandedId, setExpandedId] = useState<string | null>(null);
// 카드 헤더 클릭 → 토글
// 펼침 영역에 모든 액션(회차 생성/일시정지/재개/수락/거절/해지/거래처 점프) 표시
```
탭/필터 변경 시 `setExpandedId(null)` 로 명시적으로 닫아야 다른 탭에서 잔존 펼침 상태 노출 안 됨.

##### 상태 필터 — 백엔드 단일 status + 클라이언트 묶음 처리 (함정)

백엔드 `GET /subscriptions?status=...` 는 단일 status 만 받음. "종료" 처럼 ENDED/CANCELLED/REJECTED 를 묶어 보여주려면 전체 fetch 후 클라이언트 필터링:
```ts
interface FilterDef {
  key: string;
  label: string;
  status?: SubscriptionStatus;          // 서버 필터 (단일)
  clientStatuses?: SubscriptionStatus[];// 클라이언트 묶음 필터
}
const useServerStatus = !!def?.status && !def.clientStatuses;
useSubscriptions({ status: useServerStatus ? def.status : undefined });
```

정렬은 `STATUS_PRIORITY` 로 ACTIVE > PENDING > PAUSED > ENDED > CANCELLED > REJECTED, 동일 status 내부에서는 `next_delivery_date asc`.

##### 조건부 액션 노출 규칙

- `showAcceptReject = status === 'PENDING' && !isMyRequest` — created_by null 또는 본인이면 본인이 보낸 요청 (수락 불가)
- `showGenerate = status === 'ACTIVE'` — 회차 생성 액션
- `showPauseResume = status === 'ACTIVE' || status === 'PAUSED'`
- `showDelete = status !== 'ENDED' && status !== 'CANCELLED' && status !== 'REJECTED'` — 종결 상태는 해지 버튼 숨김

##### 거래처로 이동 — 모달 점프 + fallback 라우팅

행 액션 "거래처로 이동" 클릭 시:
1. `partners` 목록에서 `partner_user_id === counterpartUserId` 매칭
2. 매칭되면 `setSelectedPartner(partner)` → PartnerDetailModal 오픈
3. 매칭 실패 시 (거래처 미등록 등) `router.push(PARTNERS_ROUTE)` 로 fallback

##### byte-identical 유지 규칙 (정기배송 페이지)

seller/buyer 차이는 다음 4개 상수로만 한정 (diff 검증 완료):
```ts
const PAGE_ROLE: 'SELLER' | 'BUYER' = 'SELLER';  // or 'BUYER'
const PARTNERS_ROUTE = '/seller/partners';        // or '/buyer/partners'
const PAGE_DESCRIPTION = '거래처별 정기배송 일정을 관리하세요';  // or 공급처별...
const COUNTERPART_LABEL = '구매자';                // or '판매자'
```

##### TypeScript strict — `as const` 함정 (중요)

`PAGE_ROLE = 'SELLER' as const` 로 좁히면 같은 파일 내에서 `PAGE_ROLE === 'BUYER'` 비교가 TS2367 에러로 잡힌다 (literal 타입 narrowing). byte-identical 정책상 양쪽 페이지 본문이 똑같이 `PAGE_ROLE === 'SELLER' ? buyer_name : seller_name` 같은 분기를 써야 하므로 **반드시 union 타입 명시**:
```ts
// ✅ OK — 분기 비교가 양쪽 페이지에서 모두 컴파일 통과
const PAGE_ROLE: 'SELLER' | 'BUYER' = 'SELLER';

// ❌ NO — 'as const' 는 byte-identical 페이지의 분기 비교를 깨뜨림
const PAGE_ROLE = 'SELLER' as const;
```

이 패턴은 다른 byte-identical 페이지에도 동일하게 적용 — myRole 류 상수는 항상 union 타입으로 선언.

#### 구매자 재고 페이지 (`/buyer/inventory`) (검증됨, 2026-05-03)

자동 누적형(`order COMPLETED → buyer_inventories upsert`) 재고 관리 페이지. 사용자는 INSERT 권한이 없고 PATCH/DELETE 만 가능 — `useCreate*` 훅을 만들지 않는 게 핵심.

##### 타입/훅/엔드포인트 매핑

| 위치 | 정체 |
|------|-----|
| `frontend/types/inventory.ts` | `BuyerInventory`, `BuyerInventoryUpdatePayload`, `BuyerInventoryListParams`, `BuyerInventorySortBy` |
| `frontend/types/index.ts` | barrel export 등록 (함정: 잊으면 페이지에서 import 실패) |
| `frontend/hooks/useBuyerInventory.ts` | `useBuyerInventoryList`, `useBuyerInventoryDetail`, `useUpdateBuyerInventory`, `useDeleteBuyerInventory` (Create 없음) |
| `frontend/app/(dashboard)/buyer/inventory/page.tsx` | 페이지 |
| `frontend/constants/menus.ts` | buyerMenus 에 `{ label: '내 재고', href: '/buyer/inventory', icon: Boxes }` (Boxes = lucide-react) |

##### sort_by 값 — 백엔드와 정확히 일치 (함정)

백엔드 `buyer_inventory_service.list_buyer_inventory` 가 받는 정렬 키는 `recent | quantity | name` 이다. 다른 도메인의 `last_added_at | created_at` 같은 컬럼명을 그대로 쓰면 backend 가 fallback("recent") 으로 무시한다. 타입에 명시:
```ts
export type BuyerInventorySortBy = 'recent' | 'quantity' | 'name';
```

##### 검색 디바운스 + 페이지 리셋 패턴

`SearchFilterBar` 자체에는 디바운스가 없으므로 페이지 컴포넌트에서 직접:
```tsx
const [searchInput, setSearchInput] = useState('');
const [search, setSearch] = useState('');
useEffect(() => {
  const t = setTimeout(() => {
    setSearch(searchInput.trim());
    setPage(1);   // 검색어 변하면 1페이지로
  }, 300);
  return () => clearTimeout(t);
}, [searchInput]);
```
정렬 변경 시에도 `useEffect(() => setPage(1), [sortBy])` 로 1페이지 리셋.

##### 페이지네이션 — meta 기반 단순 prev/next

`SuccessResponse<BuyerInventory[]>` 의 `meta.total_pages` 를 그대로 사용. 빌더 컴포넌트가 없어 인라인으로:
```tsx
{totalPages > 1 && (
  <div className="flex items-center justify-between gap-3 pt-2">
    <p className="text-xs text-gray-500">{page} / {totalPages} 페이지</p>
    <button disabled={page <= 1 || isFetching} onClick={() => setPage(p => Math.max(1, p - 1))}>이전</button>
    <button disabled={page >= totalPages || isFetching} onClick={() => setPage(p => Math.min(totalPages, p + 1))}>다음</button>
  </div>
)}
```
`isFetching` 으로 disable → 페이지 전환 중복 클릭 방지.

##### 빈 상태 분기 — 절대 빈 vs 검색 결과 빈

자동 누적이라 "아직 입고된 적 없음" 과 "검색 결과 없음" 을 시각적으로 구분하는 게 UX 상 중요:
```tsx
const isEmpty         = !isLoading && items.length === 0 && !search;
const isFilteredEmpty = !isLoading && items.length === 0 && !!search;
// 각각 다른 EmptyState (제목/설명 다르게)
```

##### 수정 모달 — 변경 없는 필드는 payload 에서 제외

`BuyerInventoryUpdate` Pydantic 이 `Optional`(미전달=변경 안 함) 이므로 같은 값이면 키 자체를 빼야 백엔드가 불필요한 update 안 한다:
```ts
const payload: BuyerInventoryUpdatePayload = {};
if (qty !== editTarget.quantity) payload.quantity = qty;
const trimmedNotes = editNotes.trim();
const currentNotes = editTarget.notes ?? '';
if (trimmedNotes !== currentNotes) payload.notes = trimmedNotes;
if (Object.keys(payload).length === 0) { closeEdit(); return; }
```

##### 삭제 = soft delete — UI 라벨로 명시 (UX)

DELETE 가 hard delete 가 아닌 soft delete(`deleted_at` 채움) 임을 사용자에게 명시. 모달 제목 "재고 항목 숨기기", 본문에 "데이터는 보존됩니다. 같은 상품을 다시 배송완료하면 새로운 재고 항목으로 자동 추가됩니다." 안내.

##### 임베딩 join 평탄화 필드 — null 폴백 패턴

상품/판매자 soft-delete 시 백엔드가 `product_*`, `seller_*` 를 null 로 보내준다. 표시할 때 항상 폴백:
```tsx
{item.product_name ?? '상품 정보 없음'}
{item.seller_company ?? item.seller_name ?? '-'}
{categoryLabel(item.product_category)}   // CATEGORY_OPTIONS 매핑 함수, null 이면 '' 반환
```

