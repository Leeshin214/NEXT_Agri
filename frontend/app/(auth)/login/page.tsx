'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { createClient } from '@/lib/supabase/client';
import { useAuthStore, LOGIN_DURATION_MS } from '@/store/authStore';
import { api } from '@/lib/api';
import type { SuccessResponse, User, UserRole } from '@/types';

export default function LoginPage() {
  const router = useRouter();
  const supabase = createClient();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);

    const { error: authError } = await supabase.auth.signInWithPassword({
      email,
      password,
    });

    if (authError) {
      setError(
        authError.message === 'Invalid login credentials'
          ? '이메일 또는 비밀번호가 올바르지 않습니다.'
          : authError.message
      );
      setIsLoading(false);
      return;
    }

    // 세션 확인 (Supabase는 storageKey에 세션 저장 완료 상태)
    const {
      data: { session },
    } = await supabase.auth.getSession();

    if (!session) {
      setError('세션을 생성하지 못했습니다. 다시 시도해주세요.');
      setIsLoading(false);
      return;
    }

    const expiresAt = Date.now() + LOGIN_DURATION_MS;

    // 백엔드 API로 프로필 조회 (service_role → RLS 우회, 올바른 users.id 보장)
    let profile: User | null = null;
    try {
      const result = await api.get<SuccessResponse<User>>('/users/me');
      profile = result.data;
    } catch (e) {
      console.error('[Login] 백엔드 API 프로필 조회 실패, Supabase fallback 시도:', e);

      // fallback: Supabase 직접 조회
      const { data: row } = await supabase
        .from('users')
        .select('*')
        .eq('supabase_uid', session.user.id)
        .single();

      if (row) {
        profile = row as User;
      } else {
        // 메타데이터 폴백
        profile = {
          id: '',
          supabase_uid: session.user.id,
          email: session.user.email ?? '',
          name: (session.user.user_metadata?.name as string) ?? '',
          role: (session.user.user_metadata?.role as UserRole) ?? 'BUYER',
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

    // setSession으로 user + 만료 시각을 한 번에 저장
    useAuthStore.getState().setSession(profile, expiresAt);

    const redirectPath =
      profile.role === 'SELLER' ? '/seller/dashboard' : '/buyer/dashboard';
    router.replace(redirectPath);
  };

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-md">
        {/* 로고 */}
        <div className="mb-8 text-center">
          <h1 className="text-3xl font-bold text-primary-700">AgriFlow</h1>
          <p className="mt-2 text-gray-500">농산물 유통 B2B 플랫폼</p>
        </div>

        {/* 로그인 폼 */}
        <div className="rounded-xl bg-white p-8 shadow-sm">
          <h2 className="mb-6 text-xl font-semibold text-gray-900">로그인</h2>

          {error && (
            <div className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-600">
              {error}
            </div>
          )}

          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <label
                htmlFor="email"
                className="mb-1 block text-sm font-medium text-gray-700"
              >
                이메일
              </label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                placeholder="email@example.com"
                className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
              />
            </div>

            <div>
              <label
                htmlFor="password"
                className="mb-1 block text-sm font-medium text-gray-700"
              >
                비밀번호
              </label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                placeholder="비밀번호를 입력하세요"
                className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
              />
            </div>

            <button
              type="submit"
              disabled={isLoading}
              className="w-full rounded-lg bg-primary-600 py-2.5 text-sm font-medium text-white hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isLoading ? '로그인 중...' : '로그인'}
            </button>
          </form>

          <p className="mt-6 text-center text-sm text-gray-500">
            계정이 없으신가요?{' '}
            <Link
              href="/register"
              className="font-medium text-primary-600 hover:text-primary-700"
            >
              회원가입
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
