'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { createClient } from '@/lib/supabase/client';
import type { UserRole } from '@/types/user';

export default function RegisterPage() {
  const router = useRouter();
  const supabase = createClient();

  const [formData, setFormData] = useState({
    email: '',
    password: '',
    passwordConfirm: '',
    name: '',
    role: 'BUYER' as UserRole,
    company_name: '',
  });
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const handleChange = (
    e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>
  ) => {
    setFormData((prev) => ({ ...prev, [e.target.name]: e.target.value }));
  };

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (formData.password !== formData.passwordConfirm) {
      setError('비밀번호가 일치하지 않습니다.');
      return;
    }

    if (formData.password.length < 6) {
      setError('비밀번호는 6자 이상이어야 합니다.');
      return;
    }

    setIsLoading(true);

    const { error: authError } = await supabase.auth.signUp({
      email: formData.email,
      password: formData.password,
      options: {
        data: {
          name: formData.name,
          role: formData.role,
          company_name: formData.company_name,
        },
      },
    });

    if (authError) {
      setError(authError.message);
      setIsLoading(false);
      return;
    }

    // 가입 성공 → 역할별 대시보드로
    const redirectPath =
      formData.role === 'SELLER' ? '/seller/dashboard' : '/buyer/dashboard';
    router.push(redirectPath);
  };

  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-12">
      <div className="w-full max-w-md">
        {/* 로고 */}
        <div className="mb-8 text-center">
          <h1 className="text-3xl font-bold text-primary-700">AgriFlow</h1>
          <p className="mt-2 text-gray-500">농산물 유통 B2B 플랫폼</p>
        </div>

        {/* 회원가입 폼 */}
        <div className="rounded-xl bg-white p-8 shadow-sm">
          <h2 className="mb-6 text-xl font-semibold text-gray-900">
            회원가입
          </h2>

          {error && (
            <div className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-600">
              {error}
            </div>
          )}

          <form onSubmit={handleRegister} className="space-y-4">
            {/* 역할 선택 */}
            <div>
              <label className="mb-2 block text-sm font-medium text-gray-700">
                가입 유형
              </label>
              <div className="grid grid-cols-2 gap-3">
                <button
                  type="button"
                  onClick={() =>
                    setFormData((prev) => ({ ...prev, role: 'SELLER' }))
                  }
                  className={`rounded-lg border-2 px-4 py-3 text-sm font-medium transition-colors ${
                    formData.role === 'SELLER'
                      ? 'border-primary-500 bg-primary-50 text-primary-700'
                      : 'border-gray-200 text-gray-600 hover:border-gray-300'
                  }`}
                >
                  <div className="font-semibold">판매자</div>
                  <div className="mt-0.5 text-xs opacity-70">
                    농가 / 도매상 / 유통업체
                  </div>
                </button>
                <button
                  type="button"
                  onClick={() =>
                    setFormData((prev) => ({ ...prev, role: 'BUYER' }))
                  }
                  className={`rounded-lg border-2 px-4 py-3 text-sm font-medium transition-colors ${
                    formData.role === 'BUYER'
                      ? 'border-primary-500 bg-primary-50 text-primary-700'
                      : 'border-gray-200 text-gray-600 hover:border-gray-300'
                  }`}
                >
                  <div className="font-semibold">구매자</div>
                  <div className="mt-0.5 text-xs opacity-70">
                    마트 / 식자재 / 식당
                  </div>
                </button>
              </div>
            </div>

            <div>
              <label
                htmlFor="name"
                className="mb-1 block text-sm font-medium text-gray-700"
              >
                이름
              </label>
              <input
                id="name"
                name="name"
                type="text"
                value={formData.name}
                onChange={handleChange}
                required
                placeholder="홍길동"
                className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
              />
            </div>

            <div>
              <label
                htmlFor="company_name"
                className="mb-1 block text-sm font-medium text-gray-700"
              >
                업체명
              </label>
              <input
                id="company_name"
                name="company_name"
                type="text"
                value={formData.company_name}
                onChange={handleChange}
                placeholder="업체명을 입력하세요"
                className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
              />
            </div>

            <div>
              <label
                htmlFor="reg-email"
                className="mb-1 block text-sm font-medium text-gray-700"
              >
                이메일
              </label>
              <input
                id="reg-email"
                name="email"
                type="email"
                value={formData.email}
                onChange={handleChange}
                required
                placeholder="email@example.com"
                className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
              />
            </div>

            <div>
              <label
                htmlFor="reg-password"
                className="mb-1 block text-sm font-medium text-gray-700"
              >
                비밀번호
              </label>
              <input
                id="reg-password"
                name="password"
                type="password"
                value={formData.password}
                onChange={handleChange}
                required
                placeholder="6자 이상 입력하세요"
                className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
              />
            </div>

            <div>
              <label
                htmlFor="passwordConfirm"
                className="mb-1 block text-sm font-medium text-gray-700"
              >
                비밀번호 확인
              </label>
              <input
                id="passwordConfirm"
                name="passwordConfirm"
                type="password"
                value={formData.passwordConfirm}
                onChange={handleChange}
                required
                placeholder="비밀번호를 다시 입력하세요"
                className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
              />
            </div>

            <button
              type="submit"
              disabled={isLoading}
              className="w-full rounded-lg bg-primary-600 py-2.5 text-sm font-medium text-white hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isLoading ? '가입 중...' : '회원가입'}
            </button>
          </form>

          <p className="mt-6 text-center text-sm text-gray-500">
            이미 계정이 있으신가요?{' '}
            <Link
              href="/login"
              className="font-medium text-primary-600 hover:text-primary-700"
            >
              로그인
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
