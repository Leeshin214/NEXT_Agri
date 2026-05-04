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
      // SSR/초기 마운트 시점엔 false. persist 미들웨어가 localStorage 에서
      // 상태를 복원한 직후 onRehydrateStorage 콜백에서 true 로 set 한다.
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
      onRehydrateStorage: () => (_state, _error) => {
        // setState 직접 호출 — set 함수는 위 클로저 내부에서만 접근 가능
        useAuthStore.setState({ isHydrated: true });
      },
    }
  )
);
