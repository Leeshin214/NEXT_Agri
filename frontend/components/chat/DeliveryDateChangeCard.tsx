'use client';

import { Calendar, Check, X } from 'lucide-react';
import {
  useAcceptDeliveryDateChange,
  useRejectDeliveryDateChange,
} from '@/hooks/useDeliveryDateChanges';
import { cn } from '@/lib/utils';
import type { Message, MessageMetadata } from '@/types';

interface DeliveryDateChangeCardProps {
  message: Message;
  metadata: MessageMetadata;
  isMine: boolean;
}

const ROLE_LABEL: Record<'SELLER' | 'BUYER', string> = {
  SELLER: '판매자',
  BUYER: '구매자',
};

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '-';
  try {
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
 * 채팅 메시지에서 DELIVERY_DATE_CHANGE 타입 메시지를 렌더링하는 카드.
 *
 * CounterOfferCard 패턴을 그대로 차용 (sky 톤으로 색만 다름).
 * - metadata 에서 change_id, proposed_delivery_date, from_role, notes, status 읽음
 * - PENDING + 상대방 제안인 경우에만 수락/거절 버튼 노출
 * - 수락 시 캘린더/주문/메시지 캐시 invalidate (useAcceptDeliveryDateChange 내부 처리)
 */
export default function DeliveryDateChangeCard({
  message,
  metadata,
  isMine,
}: DeliveryDateChangeCardProps) {
  const changeId = metadata.change_id;
  const orderId = metadata.order_id;
  const proposedDate = metadata.proposed_delivery_date;
  const previousDate = metadata.previous_delivery_date;
  const fromRole = metadata.from_role;
  const status = metadata.status ?? 'PENDING';
  const notes = metadata.notes;

  const acceptMutation = useAcceptDeliveryDateChange(orderId ?? '');
  const rejectMutation = useRejectDeliveryDateChange(orderId ?? '');

  const canAct =
    !isMine && status === 'PENDING' && !!changeId && !!orderId;

  const handleAccept = () => {
    if (!changeId || !orderId) return;
    if (status !== 'PENDING') return;
    acceptMutation.mutate({ changeId });
  };

  const handleReject = () => {
    if (!changeId || !orderId) return;
    if (status !== 'PENDING') return;
    rejectMutation.mutate({ changeId });
  };

  const statusBadge = (() => {
    switch (status) {
      case 'ACCEPTED':
        return (
          <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2 py-0.5 text-[10px] font-medium text-green-800">
            <Check className="h-3 w-3" />
            수락됨
          </span>
        );
      case 'REJECTED':
        return (
          <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-medium text-red-800">
            <X className="h-3 w-3" />
            거절됨
          </span>
        );
      case 'SUPERSEDED':
        return (
          <span className="inline-flex items-center rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-medium text-gray-600">
            대체됨
          </span>
        );
      case 'PENDING':
      default:
        return (
          <span className="inline-flex items-center rounded-full bg-yellow-100 px-2 py-0.5 text-[10px] font-medium text-yellow-800">
            응답 대기
          </span>
        );
    }
  })();

  return (
    <div className={cn('flex', isMine ? 'justify-end' : 'justify-start')}>
      <div
        className={cn(
          'w-full max-w-[85%] rounded-xl border-2 p-4 shadow-sm',
          'border-sky-300 bg-sky-50'
        )}
      >
        <div className="mb-2 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-sky-100 text-sky-700">
              <Calendar className="h-4 w-4" />
            </span>
            <span className="text-xs font-semibold text-sky-900">
              {fromRole ? ROLE_LABEL[fromRole] : '상대방'}이(가) 납품일 변경
              요청
            </span>
          </div>
          {statusBadge}
        </div>

        <div className="mb-2">
          <p className="text-2xl font-bold text-gray-900">
            {formatDate(proposedDate)}
          </p>
          {previousDate && previousDate !== proposedDate && (
            <p className="mt-0.5 text-[11px] text-gray-500">
              기존: {formatDate(previousDate)}
            </p>
          )}
        </div>

        {notes && (
          <p className="mb-2 whitespace-pre-wrap break-words rounded-md bg-white/60 p-2 text-xs text-gray-700">
            {notes}
          </p>
        )}

        {message.content && (
          <div className="text-[10px] text-gray-500">{message.content}</div>
        )}

        {canAct && (
          <div className="mt-3 flex justify-end gap-2">
            <button
              type="button"
              onClick={handleAccept}
              disabled={acceptMutation.isPending || rejectMutation.isPending}
              className="inline-flex items-center gap-1 rounded-lg bg-primary-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50"
            >
              <Check className="h-3.5 w-3.5" />
              수락
            </button>
            <button
              type="button"
              onClick={handleReject}
              disabled={acceptMutation.isPending || rejectMutation.isPending}
              className="inline-flex items-center gap-1 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            >
              <X className="h-3.5 w-3.5" />
              거절
            </button>
          </div>
        )}
        {isMine && status === 'PENDING' && (
          <p className="mt-2 text-right text-[11px] text-gray-500">
            상대방 응답 대기 중
          </p>
        )}
      </div>
    </div>
  );
}
