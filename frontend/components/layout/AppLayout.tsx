'use client';

import { useEffect } from 'react';
import { usePathname } from 'next/navigation';
import { useAuthStore } from '@/store/authStore';
import { useUIStore } from '@/store/uiStore';
import { sellerMenus, buyerMenus } from '@/constants/menus';
import Sidebar from './Sidebar';
import TopBar from './TopBar';
import AIChatPanel from './AIChatPanel';

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user } = useAuthStore();
  const { sidebarOpen, setSidebarOpen } = useUIStore();
  const pathname = usePathname();
  const menus = user?.role === 'SELLER' ? sellerMenus : buyerMenus;
  const isFullPage = pathname === '/profile';

  // 모바일에서 기본으로 사이드바 닫기
  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth < 768) {
        setSidebarOpen(false);
      }
    };
    handleResize();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [setSidebarOpen]);

  // 모바일에서 사이드바 열린 상태일 때 오버레이 배경 클릭 시 닫기
  const handleOverlayClick = () => {
    if (window.innerWidth < 768) {
      setSidebarOpen(false);
    }
  };

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      {!isFullPage && (
        <>
          {/* 모바일 오버레이 배경 */}
          {sidebarOpen && (
            <div
              className="fixed inset-0 z-30 bg-black/40 md:hidden"
              onClick={handleOverlayClick}
            />
          )}
          <Sidebar menus={menus} currentPath={pathname} role={user?.role} />
        </>
      )}
      <div className="flex flex-1 flex-col overflow-hidden">
        <TopBar user={user} />
        <div className="flex flex-1 overflow-hidden">
          <main className="flex-1 overflow-y-auto p-4 md:p-6 min-w-0">{children}</main>
          {!isFullPage && <AIChatPanel />}
        </div>
      </div>
    </div>
  );
}
