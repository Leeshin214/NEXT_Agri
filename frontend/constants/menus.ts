import {
  LayoutDashboard,
  Calendar,
  Users,
  Package,
  ClipboardList,
  MessageCircle,
  Search,
  type LucideIcon,
} from 'lucide-react';

export interface MenuItem {
  label: string;
  href: string;
  icon: LucideIcon;
}

export const sellerMenus: MenuItem[] = [
  { label: '대시보드', href: '/seller/dashboard', icon: LayoutDashboard },
  { label: '캘린더', href: '/seller/calendar', icon: Calendar },
  { label: '거래처 목록', href: '/seller/partners', icon: Users },
  { label: '상품/재고 관리', href: '/seller/products', icon: Package },
  { label: '주문/견적 관리', href: '/seller/orders', icon: ClipboardList },
  { label: '채팅', href: '/seller/chat', icon: MessageCircle },
];

export const buyerMenus: MenuItem[] = [
  { label: '대시보드', href: '/buyer/dashboard', icon: LayoutDashboard },
  { label: '캘린더', href: '/buyer/calendar', icon: Calendar },
  { label: '거래처 목록', href: '/buyer/partners', icon: Users },
  { label: '상품 탐색', href: '/buyer/browse', icon: Search },
  { label: '주문/견적 관리', href: '/buyer/orders', icon: ClipboardList },
  { label: '채팅', href: '/buyer/chat', icon: MessageCircle },
];
