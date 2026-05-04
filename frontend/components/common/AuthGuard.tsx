'use client';

import { useEffect, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import { createClient } from '@/lib/supabase/client';
import { useAuthStore, LOGIN_DURATION_MS } from '@/store/authStore';
import { api } from '@/lib/api';
import type { SuccessResponse, User, UserRole } from '@/types';

/**
 * 보호 경로(/seller/*, /buyer/*, /profile)를 감싸는 클라이언트 인증 가드.
 *
 * 책임:
 * 1. mount 시 Supabase 세션 확인 → 없으면 /login으로 redirect
 * 2. zustand store에 user 없으면 백엔드 /users/me 호출해 setSession (또는 fallback)
 * 3. loginExpiresAt < Date.now() 인 경우 강제 signOut → /login
 * 4. onAuthStateChange로 SIGNED_OUT 감지 시 자동 로그아웃
 * 5. 역할별 라우팅: SELLER가 /buyer/* 접근 시 /seller/dashboard로, BUYER가 /seller/* 접근 시 /buyer/dashboard로
 *
 * 이전에 미들웨어가 처리하던 보호/리다이렉트를 모두 클라이언트로 이전한 형태.
 * 탭별 격리 storage 때문에 미들웨어는 세션을 식별할 수 없으므로 클라이언트 검증이 유일한 가드다.
 */
export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const { user, loginExpiresAt, isHydrated, setSession, logout } =
    useAuthStore();
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    // persist 하이드레이션이 완료되기 전엔 store 의 user/loginExpiresAt 이
    // 항상 초기값(null)으로 보이므로 그 시점에 bootstrap 을 돌리면 불필요한
    // /users/me 폴백 호출 + Supabase 세션 재확인을 거치게 된다. 더 큰 문제는
    // 채팅처럼 user.id 즉시 비교가 필요한 자식 페이지가 user=null 상태로
    // 첫 렌더되어 첫 메시지가 "상대방"으로 잘못 표시되는 버그가 생긴다는 점.
    // hydration 끝날 때까지 가드의 isReady 도 false 로 유지한다.
    if (!isHydrated) return;

    const supabase = createClient();
    let unsubscribe: (() => void) | null = null;

    async function bootstrap() {
      // 1) 만료 검증 (persist된 loginExpiresAt 기반)
      if (loginExpiresAt && loginExpiresAt < Date.now()) {
        await supabase.auth.signOut();
        queryClient.clear();
        logout();
        router.replace('/login');
        return;
      }

      // 2) 현재 세션 확인
      const {
        data: { session },
      } = await supabase.auth.getSession();

      if (!session) {
        // 세션 없음 → 로그인 페이지로
        logout();
        router.replace('/login');
        return;
      }

      // 3) store에 user 없으면 프로필 조회
      let resolvedUser: User | null = user;
      if (!resolvedUser) {
        try {
          const result = await api.get<SuccessResponse<User>>('/users/me');
          resolvedUser = result.data;
        } catch {
          // fallback: Supabase 직접 조회
          const { data: profile } = await supabase
            .from('users')
            .select('*')
            .eq('supabase_uid', session.user.id)
            .single();

          if (profile) {
            resolvedUser = profile as User;
          } else {
            // 메타데이터 폴백
            resolvedUser = {
              id: '',
              supabase_uid: session.user.id,
              email: session.user.email ?? '',
              name: (session.user.user_metadata?.name as string) ?? '',
              role:
                (session.user.user_metadata?.role as UserRole) ?? 'BUYER',
              company_name:
                (session.user.user_metadata?.company_name as string) ?? null,
              phone: null,
              profile_image: null,
              is_active: true,
              created_at: session.user.created_at ?? '',
              updated_at: session.user.created_at ?? '',
              deleted_at: null,
            };
          }
        }

        // store에 user는 있는데 expiresAt이 비어있는 비정상 상태도 수습
        const expiresAt = loginExpiresAt ?? Date.now() + LOGIN_DURATION_MS;
        setSession(resolvedUser, expiresAt);
      }

      // 4) 역할별 라우팅 가드
      if (resolvedUser) {
        const role = resolvedUser.role;
        if (role === 'SELLER' && pathname.startsWith('/buyer')) {
          router.replace('/seller/dashboard');
          return;
        }
        if (role === 'BUYER' && pathname.startsWith('/seller')) {
          router.replace('/buyer/dashboard');
          return;
        }
      }

      setIsReady(true);
    }

    bootstrap();

    // 5) 인증 상태 변경 구독 (토큰 갱신 / 외부 signOut)
    const { data: sub } = supabase.auth.onAuthStateChange(
      async (event, session) => {
        if (event === 'SIGNED_OUT') {
          queryClient.clear();
          logout();
          router.replace('/login');
        } else if (event === 'TOKEN_REFRESHED' && session) {
          // 토큰 갱신 시 만료 시각은 그대로(2일 정책 유지) — 별도 처리 없음
        }
      }
    );

    unsubscribe = () => sub.subscription.unsubscribe();

    return () => {
      if (unsubscribe) unsubscribe();
    };
    // pathname 또는 isHydrated 변화 시 재실행 — hydration 완료 직후
    // bootstrap 이 1회 트리거되도록 isHydrated 를 deps 에 포함.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname, isHydrated]);

  // 만료 검증을 라우팅 변경 시에도 실행 (페이지 이동 시 재확인)
  useEffect(() => {
    if (!isHydrated) return; // 하이드레이션 전 loginExpiresAt 은 신뢰할 수 없음
    if (loginExpiresAt && loginExpiresAt < Date.now()) {
      const supabase = createClient();
      supabase.auth.signOut().finally(() => {
        queryClient.clear();
        logout();
        router.replace('/login');
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname, isHydrated]);

  if (!isReady) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50">
        <div className="text-sm text-gray-500">불러오는 중...</div>
      </div>
    );
  }

  return <>{children}</>;
}
