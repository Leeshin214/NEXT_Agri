'use client';

import { useRouter } from 'next/navigation';
import {
  ShoppingCart,
  FileText,
  MessageCircle,
  Truck,
  Search,
  ClipboardList,
  Users,
} from 'lucide-react';
import PageHeader from '@/components/common/PageHeader';
import SummaryCard from '@/components/common/SummaryCard';
import StatusBadge from '@/components/common/StatusBadge';
import { useOrders } from '@/hooks/useOrders';

export default function BuyerDashboardPage() {
  const router = useRouter();
  const { data: ordersData } = useOrders({ limit: 5 });
  const orders = ordersData?.data ?? [];

  const activeOrders = orders.filter(
    (o) => !['COMPLETED', 'CANCELLED'].includes(o.status)
  ).length;
  const pendingQuotes = orders.filter(
    (o) => o.status === 'QUOTE_REQUESTED' || o.status === 'NEGOTIATING'
  ).length;
  const inDelivery = orders.filter((o) => o.status === 'SHIPPING').length;

  return (
    <div>
      <PageHeader title="대시보드" description="구매 현황을 한눈에 확인하세요" />

      {/* 요약 카드 */}
      <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <SummaryCard
          title="진행 중 주문"
          value={activeOrders}
          subtitle="확정 전 + 배송 전"
          icon={ShoppingCart}
          onClick={() => router.push('/buyer/orders')}
        />
        <SummaryCard
          title="견적 진행"
          value={pendingQuotes}
          subtitle="대기 + 협상 중"
          icon={FileText}
          iconColor="text-orange-600 bg-orange-100"
          onClick={() => router.push('/buyer/orders')}
        />
        <SummaryCard
          title="배송 중"
          value={inDelivery}
          subtitle="입고 예정"
          icon={Truck}
          iconColor="text-blue-600 bg-blue-100"
          onClick={() => router.push('/buyer/orders')}
        />
        <SummaryCard
          title="미확인 채팅"
          value={0}
          subtitle="읽지 않은 메시지"
          icon={MessageCircle}
          iconColor="text-purple-600 bg-purple-100"
          onClick={() => router.push('/buyer/chat')}
        />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* 최근 주문 */}
        <div className="lg:col-span-2 rounded-xl bg-white p-6 shadow-sm">
          <h2 className="mb-4 text-lg font-semibold text-gray-900">최근 주문</h2>
          {orders.length === 0 ? (
            <p className="text-sm text-gray-400">주문이 없습니다.</p>
          ) : (
            <div className="space-y-3">
              {orders.slice(0, 5).map((order) => (
                <div
                  key={order.id}
                  className="flex items-center justify-between rounded-lg border border-gray-100 p-3 hover:bg-gray-50 cursor-pointer"
                  onClick={() => router.push('/buyer/orders')}
                >
                  <div>
                    <p className="text-sm font-medium text-gray-900">{order.order_number}</p>
                    <p className="text-xs text-gray-500">
                      {order.delivery_date ? `납품일: ${order.delivery_date}` : '납품일 미정'}
                    </p>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-sm font-medium text-gray-900">
                      {order.total_amount ? `${order.total_amount.toLocaleString()}원` : '-'}
                    </span>
                    <StatusBadge status={order.status} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 빠른 작업 */}
        <div className="rounded-xl bg-white p-6 shadow-sm">
          <h2 className="mb-4 text-lg font-semibold text-gray-900">빠른 작업</h2>
          <div className="space-y-2">
            {[
              { label: '상품 탐색', icon: Search, href: '/buyer/browse', color: 'text-primary-600' },
              { label: '주문 관리', icon: ClipboardList, href: '/buyer/orders', color: 'text-blue-600' },
              { label: '거래처 확인', icon: Users, href: '/buyer/partners', color: 'text-orange-600' },
            ].map((action) => (
              <button
                key={action.label}
                onClick={() => router.push(action.href)}
                className="flex w-full items-center gap-3 rounded-lg border border-gray-100 p-3 text-left hover:bg-gray-50"
              >
                <action.icon className={`h-5 w-5 ${action.color}`} />
                <span className="text-sm font-medium text-gray-700">{action.label}</span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
