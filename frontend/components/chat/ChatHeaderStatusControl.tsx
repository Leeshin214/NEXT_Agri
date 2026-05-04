'use client';

import { useEffect, useRef, useState } from 'react';
import { ChevronDown } from 'lucide-react';
import StatusBadge from '@/components/common/StatusBadge';
import { useUpdateOrderStatus } from '@/hooks/useOrders';
import { ORDER_STATUS_OPTIONS } from '@/constants/options';
import { cn } from '@/lib/utils';
import type { OrderStatus } from '@/types';


interface ChatHeaderStatusControlProps {
  orderId: string | null;
  currentStatus: OrderStatus | null;
  role: 'seller' | 'buyer';
}

/**
 * 판매자가 직접 보낼 수 있는 다음 상태.
 * (CONFIRMED 전환은 buyer 전용 — 백엔드 가드와 동일)
 *
 * `seller/orders/page.tsx` 의 sellerNextStatusMap 과 동일하게 유지.
 */
const SELLER_NEXT_STATUS_MAP: Partial<Record<OrderStatus, OrderStatus>> = {
  CONFIRMED: 'PREPARING',
  PREPARING: 'SHIPPING',
  SHIPPING: 'COMPLETED',
};

// 구매자는 채팅 헤더에서 상태를 변경할 수 없다 — 표시만.
// 상태 변경은 주문/견적 관리 페이지에서만 허용.
const BUYER_NEXT_STATUS_MAP: Partial<Record<OrderStatus, OrderStatus>> = {};

function getStatusLabel(status: OrderStatus): string {
  return ORDER_STATUS_OPTIONS.find((o) => o.value === status)?.label ?? status;
}

/**
 * 채팅방 헤더 우측에 표시되는 주문 상태 배지 + 다음 상태 변경 드롭다운.
 *
 * - orderId 가 없으면 렌더하지 않음 (채팅방에 연결된 주문이 없을 때)
 * - currentStatus 가 없거나 CANCELLED 면 배지만 표시
 * - 다음 상태 후보가 비어 있으면 배지만 표시
 * - 후보가 있으면 ChevronDown 아이콘 + 클릭 시 드롭다운으로 다음 상태 선택
 *
 * 외부 클릭으로 드롭다운 자동 닫힘 (PriceOfferPopover 와 동일 패턴).
 */
export default function ChatHeaderStatusControl({
  orderId,
  currentStatus,
  role,
}: ChatHeaderStatusControlProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const updateStatus = useUpdateOrderStatus();

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  if (!orderId || !currentStatus) return null;

  const nextStatusMap =
    role === 'seller' ? SELLER_NEXT_STATUS_MAP : BUYER_NEXT_STATUS_MAP;
  const nextStatus = nextStatusMap[currentStatus];
  const canChange = !!nextStatus && currentStatus !== 'CANCELLED';

  const handleChange = (status: OrderStatus) => {
    if (updateStatus.isPending) return;
    setOpen(false);
    updateStatus.mutate({ id: orderId, status });
  };

  // 다음 상태가 없으면 배지만 노출
  if (!canChange) {
    return <StatusBadge status={currentStatus} />;
  }

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={updateStatus.isPending}
        className={cn(
          'inline-flex items-center gap-1 rounded-lg border border-gray-200 px-2 py-1 hover:bg-gray-50 disabled:opacity-50',
          open && 'bg-gray-50'
        )}
        title="주문 상태 변경"
      >
        <StatusBadge status={currentStatus} />
        <ChevronDown className="h-3.5 w-3.5 text-gray-400" />
      </button>

      {open && (
        <div className="absolute right-0 top-full z-20 mt-1 w-44 rounded-lg border border-gray-200 bg-white py-1 shadow-lg">
          <p className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wide text-gray-400">
            다음 상태로 변경
          </p>
          <button
            type="button"
            onClick={() => nextStatus && handleChange(nextStatus)}
            disabled={updateStatus.isPending}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-gray-700 hover:bg-primary-50 disabled:opacity-50"
          >
            <span className="text-gray-400">→</span>
            <span className="font-medium text-gray-900">
              {nextStatus ? getStatusLabel(nextStatus) : ''}
            </span>
          </button>
          {updateStatus.isError && (
            <p className="px-3 py-1.5 text-[11px] text-red-500">
              상태 변경에 실패했습니다.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
