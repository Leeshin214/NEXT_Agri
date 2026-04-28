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
  setUser: (user: User | null) => void;
  setSession: (user: User, expiresAt: number) => void;
  setLoading: (loading: boolean) => void;
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
      setUser: (user) => set({ user, isLoading: false }),
      setSession: (user, expiresAt) =>
        set({ user, loginExpiresAt: expiresAt, isLoading: false }),
      setLoading: (isLoading) => set({ isLoading }),
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
    }
  )
);
