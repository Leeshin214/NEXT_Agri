'use client';

import { Check, Clock, X } from 'lucide-react';
import {
  useAcceptCounterOffer,
  useNegotiationHistory,
  useRejectCounterOffer,
} from '@/hooks/useOrders';
import { useAuthStore } from '@/store/authStore';
import { cn } from '@/lib/utils';
import type { CounterOffer, CounterOfferStatus, FromRole } from '@/types';

interface NegotiationHistoryProps {
  orderId: string;
  /** 주문 상태 — PENDING 협상가에 대한 수락/거절 버튼 노출 가드용 */
  orderStatus?: string;
}

const statusLabel: Record<CounterOfferStatus, string> = {
  PENDING: '대기 중',
  ACCEPTED: '수락',
  REJECTED: '거절',
  SUPERSEDED: '대체됨',
};

const statusClassName: Record<CounterOfferStatus, string> = {
  PENDING: 'bg-yellow-100 text-yellow-800',
  ACCEPTED: 'bg-green-100 text-green-800',
  REJECTED: 'bg-red-100 text-red-800',
  SUPERSEDED: 'bg-gray-100 text-gray-600',
};

const roleLabel: Record<FromRole, string> = {
  SELLER: '판매자',
  BUYER: '구매자',
};

const roleBadgeClassName: Record<FromRole, string> = {
  SELLER: 'bg-blue-50 text-blue-700',
  BUYER: 'bg-primary-50 text-primary-700',
};

function formatDateTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString('ko-KR', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

export default function NegotiationHistory({
  orderId,
  orderStatus,
}: NegotiationHistoryProps) {
  const { user } = useAuthStore();
  const { data, isLoading } = useNegotiationHistory(orderId);
  const acceptMutation = useAcceptCounterOffer(orderId);
  const rejectMutation = useRejectCounterOffer(orderId);

  const offers: CounterOffer[] = data?.data ?? [];
  // 시간 역순 (최신이 위)
  const sorted = [...offers].sort((a, b) =>
    b.created_at.localeCompare(a.created_at)
  );

  // 가장 최근의 PENDING이 상대방 제시건이면 액션 노출
  const latestPending = sorted.find((o) => o.status === 'PENDING');
  const canRespond =
    latestPending &&
    user &&
    latestPending.from_user_id !== user.id &&
    (orderStatus === 'QUOTE_REQUESTED' || orderStatus === 'NEGOTIATING');

  const isMine = (offer: CounterOffer): boolean =>
    !!user && offer.from_user_id === user.id;

  const handleAccept = (offerId: string) => {
    acceptMutation.mutate({ offerId });
  };

  const handleReject = (offerId: string) => {
    rejectMutation.mutate({ offerId });
  };

  return (
    <div>
      <p className="mb-2 text-xs font-medium text-gray-500">협상 이력</p>
      {isLoading ? (
        <div className="rounded-lg bg-gray-50 p-3 text-xs text-gray-400">
          로딩 중...
        </div>
      ) : sorted.length === 0 ? (
        <div className="rounded-lg bg-gray-50 p-3 text-xs text-gray-400">
          아직 협상 이력이 없습니다.
        </div>
      ) : (
        <ul className="space-y-2">
          {sorted.map((offer) => {
            const fromRole = offer.from_role as FromRole;
            const showActions =
              canRespond &&
              latestPending &&
              latestPending.id === offer.id &&
              !isMine(offer);
            return (
              <li
                key={offer.id}
                className="rounded-lg border border-gray-200 bg-white p-3"
              >
                <div className="mb-1 flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span
                      className={cn(
                        'inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium',
                        roleBadgeClassName[fromRole]
                      )}
                    >
                      {roleLabel[fromRole]}
                    </span>
                    <span
                      className={cn(
                        'inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium',
                        statusClassName[offer.status as CounterOfferStatus]
                      )}
                    >
                      {statusLabel[offer.status as CounterOfferStatus]}
                    </span>
                  </div>
                  <span className="text-[10px] text-gray-400">
                    {formatDateTime(offer.created_at)}
                  </span>
                </div>
                <p className="text-sm font-semibold text-gray-900">
                  {offer.proposed_total_amount.toLocaleString('ko-KR')}원
                </p>
                {offer.notes && (
                  <p className="mt-1 whitespace-pre-wrap text-xs text-gray-600">
                    {offer.notes}
                  </p>
                )}
                {/* 액션 영역 */}
                {offer.status === 'PENDING' && isMine(offer) && (
                  <p className="mt-2 inline-flex items-center gap-1 text-xs text-gray-500">
                    <Clock className="h-3 w-3" />
                    상대방 응답 대기 중
                  </p>
                )}
                {showActions && (
                  <div className="mt-2 flex gap-2">
                    <button
                      onClick={() => handleAccept(offer.id)}
                      disabled={acceptMutation.isPending}
                      className="inline-flex items-center gap-1 rounded-lg bg-primary-600 px-3 py-1 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50"
                    >
                      <Check className="h-3 w-3" />
                      수락
                    </button>
                    <button
                      onClick={() => handleReject(offer.id)}
                      disabled={rejectMutation.isPending}
                      className="inline-flex items-center gap-1 rounded-lg border border-gray-300 bg-white px-3 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                    >
                      <X className="h-3 w-3" />
                      거절
                    </button>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
