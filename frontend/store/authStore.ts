import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { User } from '@/types/user';

/**
 * 로그인 유지 기간 (밀리초). 정확히 2일.
 */
export const LOGIN_DURATION_MS = 2 * 24 * 60 * 60 * 1000;

interface AuthState {
  user: User | null;
  loginExpiresAt: number | null; // epoch ms — 이 시각 이후 자동 로그아웃
  isLoading: boolean;
  /**
   * Zustand persist 미들웨어가 localStorage 에서 user/loginExpiresAt 복원을
   * 끝냈는지 여부.
   *
   * 배경: persist 의 rehydration 은 비동기로 진행되며 그 사이에는 user 가
   * 초기값(null)으로 보인다. 채팅처럼 본인/상대 판별이 즉시 필요한 화면에서는
   * 이 플래그가 true 가 되기 전에 렌더하면 첫 메시지가 "상대방 메시지"로
   * 잘못 표시되는 버그가 발생한다 (새로고침 후엔 정상). 보호 경로의 가드
   * 컴포넌트에서 이 플래그를 확인해 hydration 완료 후에만 본문을 렌더한다.
   */
  isHydrated: boolean;
  setUser: (user: User | null) => void;
  setSession: (user: User, expiresAt: number) => void;
  setLoading: (loading: boolean) => void;
  setHydrated: (hydrated: boolean) => void;
  logout: () => void;
}

/**
 * 탭별 격리 storage key.
 * - sessionStorage에 tabId가 이미 세팅돼 있을 수 있음 (Supabase client.ts와 동일 키 사용)
 * - 이 모듈은 클라이언트에서만 import되므로 typeof window 분기로 SSR 안전
 */
function getTabId(): string {
  if (typeof window === 'undefined') return 'ssr';
  let id = sessionStorage.getItem('agriflow-tab-id');
  if (!id) {
    id = crypto.randomUUID();
    sessionStorage.setItem('agriflow-tab-id', id);
  }
  return id;
}

const persistName =
  typeof window !== 'undefined'
    ? `agriflow-auth-store-${getTabId()}`
    : 'agriflow-auth-store-ssr';

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      loginExpiresAt: null,
      isLoading: true,
      // SSR/초기 마운트 시점엔 false. 클라이언트에서 hydration 완료 시
      // 아래 모듈-레벨 가드(hasHydrated/onFinishHydration/200ms fallback)에서
      // true 로 마킹된다.
      isHydrated: false,
      setUser: (user) => set({ user, isLoading: false }),
      setSession: (user, expiresAt) =>
        set({ user, loginExpiresAt: expiresAt, isLoading: false }),
      setLoading: (isLoading) => set({ isLoading }),
      setHydrated: (isHydrated) => set({ isHydrated }),
      logout: () => set({ user: null, loginExpiresAt: null }),
    }),
    {
      name: persistName,
      storage: createJSONStorage(() =>
        typeof window !== 'undefined' ? window.localStorage : (undefined as unknown as Storage)
      ),
      partialize: (state) => ({
        user: state.user,
        loginExpiresAt: state.loginExpiresAt,
      }),
      // 하이드레이션 완료 시점 (성공/실패 무관) 에 isHydrated=true 로 마킹.
      // 실패해도 이후 흐름은 user 가 null 인 채로 AuthGuard 가 /users/me 폴백
      // 로직을 타도록 진행시켜야 하므로 무조건 true 로 전환한다.
      // 단, persist 의 onRehydrateStorage 콜백은 localStorage 에 저장된 값이
      // 있을 때만 호출되므로 첫 로그인(빈 storage) 케이스에서는 호출되지 않는다.
      // 그 케이스를 커버하기 위해 아래 모듈 레벨에서 hasHydrated()/
      // onFinishHydration()/setTimeout 3중 안전장치로 보강한다.
      onRehydrateStorage: () => (_state, _error) => {
        // setState 직접 호출 — set 함수는 위 클로저 내부에서만 접근 가능
        useAuthStore.setState({ isHydrated: true });
      },
    }
  )
);

// ─────────────────────────────────────────────────────────────
// Hydration 가드 (긴급 버그 수정 — 2026-05-04)
//
// 배경:
//   Zustand persist 의 `onRehydrateStorage` 콜백은 localStorage 에 persist 데이터가
//   존재할 때만 호출된다. 즉 처음 로그인 직후처럼 storage 가 비어 있으면 콜백이
//   영원히 호출되지 않아 isHydrated 가 false 로 고정된다. AuthGuard 의 useEffect
//   가 `if (!isHydrated) return` 으로 막혀 bootstrap 이 돌지 않고
//   "불러오는 중..." 화면에서 무한 로딩 상태가 된다.
//
// 해결 (옵션 C — 3중 안전장치):
//   1) `useAuthStore.persist.hasHydrated()` 가 이미 true 면 즉시 마킹
//   2) 아니면 `onFinishHydration` 콜백에서 마킹 (정상 경로)
//   3) 200ms fallback — 어떤 이유로든 위 두 경로가 모두 동작하지 않을 때를 위한
//      마지막 안전망. 이 시점에 강제로 true 로 전환해 무한 로딩을 방지한다.
//
//   이 블록은 `typeof window !== 'undefined'` 가드로 클라이언트에서 한 번만
//   실행된다. 모듈 평가 시점에 등록되므로 AuthGuard 의 useEffect 가 처음
//   실행되기 전에 이미 hydration 결과가 반영되어 있다.
// ─────────────────────────────────────────────────────────────
if (typeof window !== 'undefined') {
  if (useAuthStore.persist.hasHydrated()) {
    // 이미 hydration 끝남 (모듈이 늦게 평가된 케이스)
    useAuthStore.setState({ isHydrated: true });
  } else {
    // 정상 hydration 완료 시점에 마킹
    useAuthStore.persist.onFinishHydration(() => {
      useAuthStore.setState({ isHydrated: true });
    });
    // 마지막 안전망: 200ms 안에도 어떤 콜백도 안 오면 강제로 true.
    // 빈 localStorage 케이스(첫 로그인) 등에서 onRehydrateStorage/onFinishHydration
    // 둘 다 호출되지 않을 수 있다는 점을 커버한다.
    setTimeout(() => {
      if (!useAuthStore.getState().isHydrated) {
        useAuthStore.setState({ isHydrated: true });
      }
    }, 200);
  }
}
