'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import { createClient } from '@/lib/supabase/client';
import { useAuthStore } from '@/store/authStore';
import { api } from '@/lib/api';
import type { SuccessResponse, User } from '@/types';

export function useAuth() {
  const { user, setUser, setLoading, logout } = useAuthStore();
  const router = useRouter();
  const supabase = createClient();
  const queryClient = useQueryClient();

  useEffect(() => {
    // 세션 동기화
    supabase.auth.getUser().then(async ({ data }) => {
      if (data.user) {
        // 백엔드 API로 프로필 조회 (service_role → RLS 우회, 올바른 users.id 보장)
        try {
          const result = await api.get<SuccessResponse<User>>('/users/me');
          setUser(result.data);
        } catch (e) {
          console.error('[useAuth] 백엔드 API 프로필 조회 실패, Supabase fallback 시도:', e);

          // fallback: Supabase 직접 조회
          const { data: profile, error: profileError } = await supabase
            .from('users')
            .select('*')
            .eq('supabase_uid', data.user.id)
            .single();

          if (profileError) {
            console.error('[useAuth] Supabase 프로필 조회 실패:', profileError.message);
          }

          if (profile) {
            setUser(profile as User);
          } else {
            // users 테이블에 레코드가 없을 때 Auth 메타데이터로 폴백
            setUser({
              id: '',
              supabase_uid: data.user.id,
              email: data.user.email ?? '',
              name: (data.user.user_metadata?.name as string) ?? '',
              role: (data.user.user_metadata?.role as 'SELLER' | 'BUYER' | 'ADMIN') ?? 'BUYER',
              company_name: (data.user.user_metadata?.company_name as string) ?? null,
              phone: null,
              profile_image: null,
              is_active: true,
              created_at: data.user.created_at ?? '',
              updated_at: data.user.created_at ?? '',
              deleted_at: null,
            });
          }
        }
      } else {
        setUser(null);
      }
    });

    // 인증 상태 변화 감지
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange(async (event) => {
      if (event === 'SIGNED_OUT') {
        queryClient.clear();
        logout();
        router.push('/login');
      }
    });

    return () => subscription.unsubscribe();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const signOut = async () => {
    await supabase.auth.signOut();
    queryClient.clear();
    logout();
    router.push('/login');
  };

  return { user, signOut };
}
