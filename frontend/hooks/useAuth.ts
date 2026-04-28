'use client';

import { useRouter } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import { createClient } from '@/lib/supabase/client';
import { useAuthStore } from '@/store/authStore';

/**
 * useAuth — TopBar 등에서 user 정보 조회와 signOut만 담당.
 *
 * 세션 동기화 / 만료 검증 / 역할별 라우팅은 모두 components/common/AuthGuard.tsx 에서 수행한다.
 * 따라서 이 훅은 store를 그대로 노출하고 signOut만 추가로 제공.
 */
export function useAuth() {
  const { user, logout } = useAuthStore();
  const router = useRouter();
  const queryClient = useQueryClient();

  const signOut = async () => {
    const supabase = createClient();
    await supabase.auth.signOut();
    queryClient.clear();
    logout();
    router.replace('/login');
  };

  return { user, signOut };
}
