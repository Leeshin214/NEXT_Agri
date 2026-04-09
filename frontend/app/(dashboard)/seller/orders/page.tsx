'use client';

import { useState } from 'react';
import PageHeader from '@/components/common/PageHeader';
import DataTable, { type Column } from '@/components/common/DataTable';
import StatusBadge from '@/components/common/StatusBadge';
import { useOrders, useUpdateOrderStatus } from '@/hooks/useOrders';
import { ORDER_STATUS_OPTIONS } from '@/constants/options';
import type { Order, OrderStatus } from '@/types';
import { cn } from '@/lib/utils';

const tabs = [
  { key: 'pending', label: '견적/진행', statuses: ['QUOTE_REQUESTED', 'NEGOTIATING', 'CONFIRMED', 'PREPARING'] },
  { key: 'shipping', label: '배송중', statuses: ['SHIPPING'] },
  { key: 'done', label: '완료/취소', statuses: ['COMPLETED', 'CANCELLED'] },
];

export default function SellerOrdersPage() {
  const [activeTab, setActiveTab] = useState('pending');
  const [selectedOrder, setSelectedOrder] = useState<Order | null>(null);

  const { data, isLoading } = useOrders();
  const updateStatus = useUpdateOrderStatus();
  const allOrders = data?.data ?? [];

  const activeStatuses = tabs.find((t) => t.key === activeTab)?.statuses ?? [];
  const filteredOrders = allOrders.filter((o) =>
    activeStatuses.includes(o.status)
  );

  const nextStatusMap: Record<string, OrderStatus> = {
    QUOTE_REQUESTED: 'NEGOTIATING',
    NEGOTIATING: 'CONFIRMED',
    CONFIRMED: 'PREPARING',
    PREPARING: 'SHIPPING',
    SHIPPING: 'COMPLETED',
  };

  const handleNextStatus = (order: Order) => {
    const next = nextStatusMap[order.status];
    if (next) {
      updateStatus.mutate({ id: order.id, status: next });
    }
  };

  const columns: Column<Order>[] = [
    {
      key: 'order_number',
      header: '주문번호',
      render: (item) => (
        <span className="font-medium text-gray-900">{item.order_number}</span>
      ),
    },
    {
      key: 'total_amount',
      header: '금액',
      render: (item) => (
        <span className="text-gray-900">
          {item.total_amount ? `${item.total_amount.toLocaleString()}원` : '-'}
        </span>
      ),
    },
    {
      key: 'delivery_date',
      header: '납품일',
      render: (item) => (
        <span className="text-gray-600">{item.delivery_date || '미정'}</span>
      ),
    },
    {
      key: 'status',
      header: '상태',
      render: (item) => <StatusBadge status={item.status} />,
    },
    {
      key: 'actions',
      header: '',
      className: 'text-right',
      render: (item) => {
        const next = nextStatusMap[item.status];
        if (!next) return null;
        const nextLabel = ORDER_STATUS_OPTIONS.find((o) => o.value === next)?.label;
        return (
          <button
            onClick={(e) => { e.stopPropagation(); handleNextStatus(item); }}
            className="rounded-lg bg-primary-50 px-3 py-1 text-xs font-medium text-primary-700 hover:bg-primary-100"
          >
            {nextLabel} 처리
          </button>
        );
      },
    },
  ];

  return (
    <div>
      <PageHeader
        title="주문/견적 관리"
        description="받은 견적 요청 및 주문을 관리하세요"
      />

      {/* 탭 */}
      <div className="mb-4 flex gap-1 rounded-lg bg-gray-100 p-1">
        {tabs.map((tab) => {
          const count = allOrders.filter((o) =>
            tab.statuses.includes(o.status)
          ).length;
          return (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={cn(
                'flex-1 rounded-md px-4 py-2 text-sm font-medium transition-colors',
                activeTab === tab.key
                  ? 'bg-white text-gray-900 shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              )}
            >
              {tab.label} ({count})
            </button>
          );
        })}
      </div>

      {isLoading ? (
        <div className="py-12 text-center text-sm text-gray-400">로딩 중...</div>
      ) : (
        <DataTable
          columns={columns}
          data={filteredOrders}
          onRowClick={setSelectedOrder}
          emptyMessage="해당 상태의 주문이 없습니다."
        />
      )}

      {/* 주문 상세 슬라이드 패널 */}
      {selectedOrder && (
        <div className="fixed inset-y-0 right-0 z-40 w-full sm:w-96 bg-white shadow-xl">
          <div className="flex h-full flex-col">
            <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
              <h2 className="text-lg font-semibold text-gray-900">
                {selectedOrder.order_number}
              </h2>
              <button
                onClick={() => setSelectedOrder(null)}
                className="text-gray-400 hover:text-gray-600"
              >
                닫기
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-6 space-y-4">
              <div>
                <p className="text-xs text-gray-500">상태</p>
                <StatusBadge status={selectedOrder.status} />
              </div>
              <div>
                <p className="text-xs text-gray-500">총 금액</p>
                <p className="text-lg font-semibold text-gray-900">
                  {selectedOrder.total_amount
                    ? `${selectedOrder.total_amount.toLocaleString()}원`
                    : '-'}
                </p>
              </div>
              <div>
                <p className="text-xs text-gray-500">납품일</p>
                <p className="text-sm text-gray-900">{selectedOrder.delivery_date || '미정'}</p>
              </div>
              {selectedOrder.delivery_address && (
                <div>
                  <p className="text-xs text-gray-500">배송지</p>
                  <p className="text-sm text-gray-900">{selectedOrder.delivery_address}</p>
                </div>
              )}
              {selectedOrder.notes && (
                <div>
                  <p className="text-xs text-gray-500">메모</p>
                  <p className="text-sm text-gray-900">{selectedOrder.notes}</p>
                </div>
              )}
              {selectedOrder.items.length > 0 && (
                <div>
                  <p className="mb-2 text-xs text-gray-500">주문 항목</p>
                  <div className="space-y-2">
                    {selectedOrder.items.map((item) => (
                      <div key={item.id} className="rounded-lg bg-gray-50 p-3">
                        <div className="flex justify-between text-sm">
                          <span className="text-gray-700">수량: {item.quantity}</span>
                          <span className="font-medium text-gray-900">
                            {item.subtotal.toLocaleString()}원
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
