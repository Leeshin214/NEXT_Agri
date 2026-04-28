'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { createClient } from '@/lib/supabase/client';
import { useAuthStore } from '@/store/authStore';

/**
 * 루트 진입점.
 * - 미들웨어가 비활성화됐으므로 클라이언트에서 세션을 확인해 분기한다.
 * - 세션 + user role 있음 → 역할별 대시보드
 * - 그 외 → /login
 */
export default function Home() {
  const router = useRouter();
  const { user, loginExpiresAt } = useAuthStore();

  useEffect(() => {
    async function decide() {
      const supabase = createClient();
      const {
        data: { session },
      } = await supabase.auth.getSession();

      const expired = loginExpiresAt != null && loginExpiresAt < Date.now();

      if (!session || expired) {
        router.replace('/login');
        return;
      }

      const role = user?.role;
      if (role === 'SELLER') {
        router.replace('/seller/dashboard');
      } else if (role === 'BUYER') {
        router.replace('/buyer/dashboard');
      } else {
        // role 정보가 아직 store에 없을 때는 일단 로그인으로 보내 AuthGuard가 처리
        router.replace('/login');
      }
    }
    decide();
  }, [router, user, loginExpiresAt]);

  return (
    <div className="flex h-screen items-center justify-center bg-gray-50">
      <div className="text-sm text-gray-500">불러오는 중...</div>
    </div>
  );
}
