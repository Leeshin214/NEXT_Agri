'use client';

import { usePathname } from 'next/navigation';
import { useAuthStore } from '@/store/authStore';
import { sellerMenus, buyerMenus } from '@/constants/menus';
import Sidebar from './Sidebar';
import TopBar from './TopBar';
import AIChatPanel from './AIChatPanel';

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user } = useAuthStore();
  const pathname = usePathname();
  const menus = user?.role === 'SELLER' ? sellerMenus : buyerMenus;
  const isFullPage = pathname === '/profile';

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      {!isFullPage && <Sidebar menus={menus} currentPath={pathname} role={user?.role} />}
      <div className="flex flex-1 flex-col overflow-hidden">
        <TopBar user={user} />
        <div className="flex flex-1 overflow-hidden">
          <main className="flex-1 overflow-y-auto p-6 min-w-0">{children}</main>
          {!isFullPage && <AIChatPanel />}
        </div>
      </div>
    </div>
  );
}
