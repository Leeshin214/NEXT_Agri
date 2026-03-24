'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { createClient } from '@/lib/supabase/client';

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

    // 역할 확인 후 리다이렉트
    const {
      data: { user },
    } = await supabase.auth.getUser();

    if (user) {
      const { data: profile } = await supabase
        .from('users')
        .select('role')
        .eq('supabase_uid', user.id)
        .single();

      const redirectPath =
        profile?.role === 'SELLER' ? '/seller/dashboard' : '/buyer/dashboard';
      router.push(redirectPath);
    }
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
