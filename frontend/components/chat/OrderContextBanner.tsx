'use client';

import { useState } from 'react';
import { ChevronDown, ChevronUp, ClipboardList, History } from 'lucide-react';
import StatusBadge from '@/components/common/StatusBadge';
import { useOrder } from '@/hooks/useOrders';
import NegotiationHistory from '@/components/chat/NegotiationHistory';

interface OrderContextBannerProps {
  orderId: string;
  /** 주문 상세 페이지 라우팅용. 'seller' | 'buyer' */
  role: 'seller' | 'buyer';
  /** 주문 상세 페이지 이동 핸들러. 우선순위 1. */
  onOpenOrder?: (orderId: string) => void;
}

/**
 * 채팅방 헤더 아래에 표시되는 주문 컨텍스트 배너.
 * room.order_id 가 있을 때만 채팅 페이지에서 렌더한다.
 *
 * - 상품명 첫 항목 + 외 N건 / 상태 배지 / 총액
 * - 우측 "이력" 토글 버튼 → 펼치면 NegotiationHistory 타임라인 표시
 * - 우측 "주문 상세 보기" 버튼 → onOpenOrder 콜백 우선,
 *   없으면 /{role}/orders?id=... 로 라우팅 (현재 구조상 콜백 권장)
 *
 * 협상 이력 토글:
 *   - 컴포넌트 내부 useState 만 사용 (전역 X)
 *   - 기본 false (접힘) — 모바일/데스크톱 모두 안전한 디폴트
 *   - 닫혔을 때 기존 1줄 layout 그대로 유지
 */
export default function OrderContextBanner({
  orderId,
  role,
  onOpenOrder,
}: OrderContextBannerProps) {
  const { data, isLoading, error } = useOrder(orderId);
  const order = data?.data;
  const [historyOpen, setHistoryOpen] = useState(false);

  if (isLoading) {
    return (
      <div className="border-b border-gray-200 bg-gray-50 px-4 py-2 text-xs text-gray-500">
        주문 정보를 불러오는 중...
      </div>
    );
  }

  // 주문이 없거나 에러면 배너 숨김 (요구사항)
  if (error || !order) return null;

  const firstName = order.items?.[0]?.product_name ?? '상품 정보 없음';
  const extra =
    order.items.length > 1 ? ` 외 ${order.items.length - 1}건` : '';

  const handleClick = () => {
    if (onOpenOrder) {
      onOpenOrder(order.id);
      return;
    }
    // 폴백 라우팅 — 페이지에 onOpenOrder 가 없을 때만 사용
    if (typeof window !== 'undefined') {
      window.location.href = `/${role}/orders?id=${order.id}`;
    }
  };

  return (
    <div className="border-b border-primary-100 bg-primary-50/40">
      <div className="flex items-start justify-between gap-3 px-4 py-2.5">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <ClipboardList className="h-4 w-4 flex-shrink-0 text-primary-600" />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <p className="truncate text-xs font-medium text-gray-900">
                {firstName}
                {extra}
              </p>
              <StatusBadge status={order.status} />
            </div>
            <p className="mt-0.5 truncate text-[11px] text-gray-600">
              {order.order_number}
              {typeof order.total_amount === 'number' && (
                <>
                  {' · '}
                  <span className="font-medium text-gray-800">
                    {order.total_amount.toLocaleString('ko-KR')}원
                  </span>
                </>
              )}
            </p>
          </div>
        </div>
        <div className="flex flex-shrink-0 items-center gap-1.5">
          <button
            type="button"
            onClick={() => setHistoryOpen((v) => !v)}
            aria-expanded={historyOpen}
            aria-controls={`negotiation-history-${order.id}`}
            className="inline-flex items-center gap-1 rounded-lg border border-primary-300 bg-white px-2.5 py-1.5 text-xs font-medium text-primary-700 hover:bg-primary-50"
          >
            <History className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">이력</span>
            {historyOpen ? (
              <ChevronUp className="h-3 w-3" />
            ) : (
              <ChevronDown className="h-3 w-3" />
            )}
          </button>
          <button
            type="button"
            onClick={handleClick}
            className="rounded-lg border border-primary-300 bg-white px-3 py-1.5 text-xs font-medium text-primary-700 hover:bg-primary-50"
          >
            <span className="hidden sm:inline">주문 상세 보기</span>
            <span className="sm:hidden">상세</span>
          </button>
        </div>
      </div>
      {historyOpen && (
        <div
          id={`negotiation-history-${order.id}`}
          className="border-t border-primary-100 bg-white/60"
        >
          <NegotiationHistory orderId={order.id} />
        </div>
      )}
    </div>
  );
}
