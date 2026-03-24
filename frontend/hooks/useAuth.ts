'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { createClient } from '@/lib/supabase/client';
import { useAuthStore } from '@/store/authStore';

export function useAuth() {
  const { user, setUser, setLoading, logout } = useAuthStore();
  const router = useRouter();
  const supabase = createClient();

  useEffect(() => {
    // 세션 동기화
    supabase.auth.getUser().then(async ({ data }) => {
      if (data.user) {
        const { data: profile } = await supabase
          .from('users')
          .select('*')
          .eq('supabase_uid', data.user.id)
          .single();

        if (profile) {
          setUser(profile);
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
      } else {
        setUser(null);
      }
    });

    // 인증 상태 변화 감지
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange(async (event) => {
      if (event === 'SIGNED_OUT') {
        logout();
        router.push('/login');
      }
    });

    return () => subscription.unsubscribe();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const signOut = async () => {
    await supabase.auth.signOut();
    logout();
    router.push('/login');
  };

  return { user, signOut };
}
