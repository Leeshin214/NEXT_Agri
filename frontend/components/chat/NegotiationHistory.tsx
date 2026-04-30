'use client';

import { useNegotiationHistory } from '@/hooks/useOrders';
import { cn } from '@/lib/utils';
import type { CounterOffer, CounterOfferStatus, FromRole } from '@/types';

interface ChatNegotiationHistoryProps {
  orderId: string;
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

/**
 * 분 단위 상대 시간 — 1분 미만: 방금 전, 24시간 미만: N분/시간 전, 그 외: 일자.
 */
function formatRelativeTime(iso: string): string {
  try {
    const now = Date.now();
    const past = new Date(iso).getTime();
    const diffSec = Math.max(0, Math.floor((now - past) / 1000));
    if (diffSec < 60) return '방금 전';
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin}분 전`;
    const diffHour = Math.floor(diffMin / 60);
    if (diffHour < 24) return `${diffHour}시간 전`;
    const diffDay = Math.floor(diffHour / 24);
    if (diffDay < 7) return `${diffDay}일 전`;
    return new Date(iso).toLocaleDateString('ko-KR', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    });
  } catch {
    return iso;
  }
}

/**
 * 채팅방 헤더 OrderContextBanner 안에서 펼쳐지는 협상 이력 타임라인.
 *
 * - components/common/NegotiationHistory.tsx 와 달리 액션 버튼(수락/거절) 미포함.
 *   채팅 메시지의 COUNTER_OFFER 카드(MessageBubble)에 동일 액션이 이미 있으므로
 *   여기서는 읽기 전용 요약 타임라인만 제공한다.
 * - 시간 역순. 빈 배열이면 미니 placeholder, 에러는 조용히 숨김.
 */
export default function NegotiationHistory({
  orderId,
}: ChatNegotiationHistoryProps) {
  const { data, isLoading, error } = useNegotiationHistory(orderId);

  if (error) return null;

  const offers: CounterOffer[] = data?.data ?? [];
  const sorted = [...offers].sort((a, b) =>
    b.created_at.localeCompare(a.created_at)
  );

  if (isLoading) {
    return (
      <div className="px-4 pb-3 text-[11px] text-gray-400">
        협상 이력을 불러오는 중...
      </div>
    );
  }

  if (sorted.length === 0) {
    return (
      <div className="px-4 pb-3 text-[11px] text-gray-400">
        협상 이력이 없습니다.
      </div>
    );
  }

  return (
    <div className="px-4 pb-3">
      <ol className="relative space-y-2 border-l border-primary-200 pl-3">
        {sorted.map((offer) => {
          const fromRole = offer.from_role as FromRole;
          const offerStatus = offer.status as CounterOfferStatus;
          return (
            <li key={offer.id} className="relative">
              {/* dot — border-l 위에 정확히 위치하도록 absolute */}
              <span
                className={cn(
                  'absolute -left-[17px] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-white',
                  offerStatus === 'ACCEPTED'
                    ? 'bg-green-500'
                    : offerStatus === 'REJECTED'
                      ? 'bg-red-500'
                      : offerStatus === 'SUPERSEDED'
                        ? 'bg-gray-400'
                        : 'bg-yellow-400'
                )}
                aria-hidden="true"
              />
              <div className="rounded-lg border border-gray-200 bg-white px-2.5 py-2">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span
                    className={cn(
                      'inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium',
                      roleBadgeClassName[fromRole]
                    )}
                  >
                    {roleLabel[fromRole]}
                  </span>
                  <span
                    className={cn(
                      'inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium',
                      statusClassName[offerStatus]
                    )}
                  >
                    {statusLabel[offerStatus]}
                  </span>
                  <span className="ml-auto text-[10px] text-gray-400">
                    {formatRelativeTime(offer.created_at)}
                  </span>
                </div>
                <p className="mt-1 text-sm font-semibold text-gray-900">
                  {offer.proposed_total_amount.toLocaleString('ko-KR')}원
                </p>
                {offer.notes && (
                  <p className="mt-0.5 line-clamp-2 whitespace-pre-wrap text-[11px] text-gray-600">
                    {offer.notes}
                  </p>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
