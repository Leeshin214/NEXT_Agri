'use client';

import Link from 'next/link';
import { cn } from '@/lib/utils';
import { useUIStore } from '@/store/uiStore';
import { ChevronLeft } from 'lucide-react';
import type { MenuItem } from '@/constants/menus';
import type { UserRole } from '@/types/user';

interface SidebarProps {
  menus: MenuItem[];
  currentPath: string;
  role?: UserRole;
}

export default function Sidebar({ menus, currentPath, role }: SidebarProps) {
  const { sidebarOpen, toggleSidebar } = useUIStore();

  return (
    <aside
      className={cn(
        'relative flex flex-col border-r border-gray-200 bg-white transition-all duration-200',
        sidebarOpen ? 'w-60' : 'w-16'
      )}
    >
      {/* 로고 */}
      <div className="flex h-16 items-center border-b border-gray-200 px-4">
        {sidebarOpen && (
          <Link href={role === 'SELLER' ? '/seller/dashboard' : '/buyer/dashboard'}>
            <span className="text-xl font-bold text-primary-700">AgriFlow</span>
          </Link>
        )}
        <button
          onClick={toggleSidebar}
          className={cn(
            'flex h-8 w-8 items-center justify-center rounded-lg text-gray-400 hover:bg-gray-100 hover:text-gray-600',
            sidebarOpen ? 'ml-auto' : 'mx-auto'
          )}
        >
          <ChevronLeft
            className={cn(
              'h-4 w-4 transition-transform',
              !sidebarOpen && 'rotate-180'
            )}
          />
        </button>
      </div>

      {/* 역할 배지 */}
      {sidebarOpen && (
        <div className="border-b border-gray-200 px-4 py-3">
          <span
            className={cn(
              'inline-block rounded-full px-3 py-1 text-xs font-medium',
              role === 'SELLER'
                ? 'bg-primary-100 text-primary-700'
                : 'bg-blue-100 text-blue-700'
            )}
          >
            {role === 'SELLER' ? '판매자' : '구매자'}
          </span>
        </div>
      )}

      {/* 메뉴 */}
      <nav className="flex-1 overflow-y-auto px-2 py-3">
        {menus.map((menu) => {
          const isActive =
            currentPath === menu.href ||
            currentPath.startsWith(menu.href + '/');
          const Icon = menu.icon;

          return (
            <Link
              key={menu.href}
              href={menu.href}
              className={cn(
                'mb-1 flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors',
                isActive
                  ? 'bg-primary-50 text-primary-700'
                  : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900',
                !sidebarOpen && 'justify-center px-0'
              )}
              title={!sidebarOpen ? menu.label : undefined}
            >
              <Icon className="h-5 w-5 flex-shrink-0" />
              {sidebarOpen && <span>{menu.label}</span>}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
