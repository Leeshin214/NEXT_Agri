'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { User as UserIcon, Building2, Phone, Mail, Edit2, Save, X, ArrowLeft } from 'lucide-react';
import { useAuthStore } from '@/store/authStore';
import { api } from '@/lib/api';
import PageHeader from '@/components/common/PageHeader';
import type { User } from '@/types/user';
import type { SuccessResponse } from '@/types/api';

const ROLE_LABEL: Record<string, string> = {
  SELLER: '판매자',
  BUYER: '구매자',
  ADMIN: '관리자',
};

export default function ProfilePage() {
  const router = useRouter();
  const { user, setUser } = useAuthStore();
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({
    name: user?.name ?? '',
    company_name: user?.company_name ?? '',
    phone: user?.phone ?? '',
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // 마운트 시 최신 사용자 데이터를 API에서 직접 가져와 store 갱신
  useEffect(() => {
    api.get<SuccessResponse<User>>('/users/me').then((res) => {
      setUser(res.data);
    }).catch(() => {
      // 네트워크 오류 등은 조용히 무시 — 기존 store 값으로 표시
    });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // user가 나중에 채워질 때(persist 복원 포함) form을 동기화
  useEffect(() => {
    if (user && !editing) {
      setForm({
        name: user.name ?? '',
        company_name: user.company_name ?? '',
        phone: user.phone ?? '',
      });
    }
  }, [user, editing]);

  const handleSave = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await api.patch<SuccessResponse<User>>('/users/me', form);
      setUser(res.data);
      setEditing(false);
    } catch {
      setError('저장에 실패했습니다. 다시 시도해주세요.');
    } finally {
      setLoading(false);
    }
  };

  const handleCancel = () => {
    setForm({
      name: user?.name ?? '',
      company_name: user?.company_name ?? '',
      phone: user?.phone ?? '',
    });
    setEditing(false);
    setError('');
  };

  const joinedAt = user?.created_at
    ? new Date(user.created_at).toLocaleDateString('ko-KR', {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
      })
    : '-';

  return (
    <div className="mx-auto max-w-xl">
      <button
        onClick={() => router.back()}
        className="mb-4 flex items-center gap-1.5 text-sm text-gray-400 hover:text-gray-600"
      >
        <ArrowLeft className="h-4 w-4" />
        뒤로가기
      </button>
      <PageHeader
        title="마이페이지"
        description="개인정보를 확인하고 수정할 수 있습니다"
        action={
          !editing ? (
            <button
              onClick={() => setEditing(true)}
              className="flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              <Edit2 className="h-4 w-4" />
              정보 수정
            </button>
          ) : undefined
        }
      />

      <div className="rounded-xl bg-white p-6 shadow-sm">
        {/* 아바타 + 역할 */}
        <div className="mb-6 flex flex-col items-center gap-3">
          <div className="flex h-20 w-20 items-center justify-center rounded-full bg-primary-100 text-primary-700">
            <UserIcon className="h-9 w-9" />
          </div>
          {user?.role && (
            <span className="rounded-full bg-primary-50 px-3 py-1 text-xs font-medium text-primary-700">
              {ROLE_LABEL[user.role] ?? user.role}
            </span>
          )}
        </div>

        {/* 정보 필드 */}
        <div className="space-y-5">
          {/* 이메일 (읽기 전용) */}
          <div>
            <label className="mb-1 flex items-center gap-1.5 text-xs font-medium text-gray-500">
              <Mail className="h-3.5 w-3.5" />
              이메일
            </label>
            <p className="rounded-lg bg-gray-50 px-3 py-2.5 text-sm text-gray-500">
              {user?.email ?? '-'}
            </p>
          </div>

          {/* 이름 */}
          <div>
            <label className="mb-1 flex items-center gap-1.5 text-xs font-medium text-gray-500">
              <UserIcon className="h-3.5 w-3.5" />
              이름
            </label>
            {editing ? (
              <input
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
              />
            ) : (
              <p className="rounded-lg bg-gray-50 px-3 py-2.5 text-sm text-gray-900">
                {user?.name || '-'}
              </p>
            )}
          </div>

          {/* 회사명 */}
          <div>
            <label className="mb-1 flex items-center gap-1.5 text-xs font-medium text-gray-500">
              <Building2 className="h-3.5 w-3.5" />
              회사명
            </label>
            {editing ? (
              <input
                value={form.company_name}
                onChange={(e) => setForm((f) => ({ ...f, company_name: e.target.value }))}
                className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
              />
            ) : (
              <p className="rounded-lg bg-gray-50 px-3 py-2.5 text-sm text-gray-900">
                {user?.company_name || '-'}
              </p>
            )}
          </div>

          {/* 연락처 */}
          <div>
            <label className="mb-1 flex items-center gap-1.5 text-xs font-medium text-gray-500">
              <Phone className="h-3.5 w-3.5" />
              연락처
            </label>
            {editing ? (
              <input
                value={form.phone}
                onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))}
                placeholder="010-0000-0000"
                className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
              />
            ) : (
              <p className="rounded-lg bg-gray-50 px-3 py-2.5 text-sm text-gray-900">
                {user?.phone || '-'}
              </p>
            )}
          </div>
        </div>

        {/* 수정 버튼 */}
        {editing && (
          <div className="mt-6 flex justify-end gap-2">
            {error && <p className="mr-auto self-center text-xs text-red-500">{error}</p>}
            <button
              onClick={handleCancel}
              className="flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
            >
              <X className="h-4 w-4" />
              취소
            </button>
            <button
              onClick={handleSave}
              disabled={loading}
              className="flex items-center gap-1.5 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50"
            >
              <Save className="h-4 w-4" />
              {loading ? '저장 중...' : '저장'}
            </button>
          </div>
        )}

        {/* 계정 정보 */}
        <div className="mt-6 border-t border-gray-100 pt-4">
          <p className="text-xs text-gray-400">가입일: {joinedAt}</p>
        </div>
      </div>
    </div>
  );
}
