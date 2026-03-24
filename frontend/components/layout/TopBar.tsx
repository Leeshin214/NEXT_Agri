'use client';

import { useEffect, useRef, useState } from 'react';
import { Bell, LogOut, User as UserIcon, Settings } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/hooks/useAuth';
import type { User } from '@/types/user';

interface TopBarProps {
  user: User | null;
}

export default function TopBar({ user }: TopBarProps) {
  const { signOut } = useAuth();
  const router = useRouter();
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  return (
    <header className="flex h-16 items-center justify-between border-b border-gray-200 bg-white px-6">
      {/* 좌측: 페이지 타이틀 영역 */}
      <div />

      {/* 우측: 사용자 정보 */}
      <div className="flex items-center gap-4">
        {/* 알림 */}
        <button className="relative flex h-9 w-9 items-center justify-center rounded-lg text-gray-400 hover:bg-gray-100 hover:text-gray-600">
          <Bell className="h-5 w-5" />
        </button>

        {/* 프로필 드롭다운 */}
        <div className="relative" ref={dropdownRef}>
          <button
            onClick={() => setDropdownOpen((prev) => !prev)}
            className="flex items-center gap-3 rounded-lg px-2 py-1 hover:bg-gray-50"
          >
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-primary-100 text-primary-700">
              <UserIcon className="h-4 w-4" />
            </div>
            <div className="hidden sm:block text-left">
              <p className="text-sm font-medium text-gray-900">
                {user?.name || '사용자'}
              </p>
              <p className="text-xs text-gray-500">
                {user?.company_name || ''}
              </p>
            </div>
          </button>

          {/* 드롭다운 메뉴 */}
          {dropdownOpen && (
            <div className="absolute right-0 top-12 z-50 w-44 rounded-xl border border-gray-100 bg-white py-1 shadow-lg">
              <button
                onClick={() => {
                  setDropdownOpen(false);
                  router.push('/profile');
                }}
                className="flex w-full items-center gap-2 px-4 py-2.5 text-sm text-gray-700 hover:bg-gray-50"
              >
                <Settings className="h-4 w-4 text-gray-400" />
                마이페이지
              </button>
              <div className="my-1 border-t border-gray-100" />
              <button
                onClick={() => {
                  setDropdownOpen(false);
                  signOut();
                }}
                className="flex w-full items-center gap-2 px-4 py-2.5 text-sm text-red-500 hover:bg-red-50"
              >
                <LogOut className="h-4 w-4" />
                로그아웃
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
