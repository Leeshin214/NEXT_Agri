'use client';

import { Check, X, DollarSign, Package, Ban } from 'lucide-react';
import {
  useAcceptCounterOffer,
  useRejectCounterOffer,
} from '@/hooks/useOrders';
import { useAuthStore } from '@/store/authStore';
import StatusBadge from '@/components/common/StatusBadge';
import DeliveryDateChangeCard from '@/components/chat/DeliveryDateChangeCard';
import NegotiationDraftCard from '@/components/chat/NegotiationDraftCard';
import { cn } from '@/lib/utils';
import type { Message, MessageMetadata, NegotiationDraft } from '@/types';

interface MessageBubbleProps {
  message: Message;
  /**
   * 부모(채팅 페이지)에서 직접 주입하는 현재 사용자 id.
   * 지정하면 useAuthStore 의 user 보다 우선해 본인/상대 판별에 사용한다.
   *
   * 배경: useAuthStore 는 Zustand persist 를 사용하므로 첫 렌더 시점에는
   * 하이드레이션 전이라 user 가 null 일 수 있다. 그 결과 isMine 이 false 로
   * 고정돼 모든 메시지가 왼쪽에 표시되는 버그가 발생한다 (새로고침 후엔 정상).
   * 부모 페이지에서 user.id 를 prop 으로 내려주면 하이드레이션 타이밍과
   * 무관하게 일관된 판별이 가능하다.
   */
  currentUserId?: string;
  /**
   * US-2 협상 의도 감지 카드 [등록] 클릭 핸들러.
   * 본인 발신 TEXT 메시지에 metadata.draft_negotiation 이 있을 때만 카드가 렌더되며,
   * 클릭 시 부모(채팅 페이지)가 PriceOfferPopover 를 prefill 한 채로 연다.
   */
  onAcceptNegotiationDraft?: (draft: NegotiationDraft) => void;
  /** US-2 협상 의도 감지 카드 [무시] 클릭 핸들러 (PATCH dismiss API) */
  onDismissNegotiationDraft?: (messageId: string) => void;
  /** dismiss API 진행 중 표시용 (선택) */
  isDismissingNegotiationDraft?: boolean;
}

const ROLE_LABEL: Record<'SELLER' | 'BUYER', string> = {
  SELLER: '판매자',
  BUYER: '구매자',
};

function formatAmount(amount: number | undefined | null): string {
  if (typeof amount !== 'number' || !Number.isFinite(amount)) return '-';
  return `${amount.toLocaleString('ko-KR')}원`;
}

/**
 * message_type 에 따라 분기 렌더하는 통합 메시지 컴포넌트.
 *
 * 본인/상대 판별: currentUserId(prop) → useAuthStore.user.id 순으로 우선.
 * (metadata.from_role 만으로는 같은 역할 두 사용자를 구분하지 못함)
 */
export default function MessageBubble({
  message,
  currentUserId,
  onAcceptNegotiationDraft,
  onDismissNegotiationDraft,
  isDismissingNegotiationDraft,
}: MessageBubbleProps) {
  const { user } = useAuthStore();
  const effectiveUserId = currentUserId ?? user?.id;
  const isMine = !!effectiveUserId && message.sender_id === effectiveUserId;
  const type = message.message_type ?? 'TEXT';
  const metadata = (message.metadata ?? {}) as MessageMetadata;

  switch (type) {
    case 'SYSTEM':
      return <SystemNotice content={message.content} metadata={metadata} />;

    case 'COUNTER_OFFER':
      return (
        <CounterOfferCard
          message={message}
          metadata={metadata}
          isMine={isMine}
        />
      );

    case 'OFFER_ACCEPTED':
      return <OfferAcceptedCard metadata={metadata} content={message.content} />;

    case 'OFFER_REJECTED':
      return <OfferRejectedCard content={message.content} />;

    case 'ORDER_STATUS':
      return <OrderStatusCard metadata={metadata} content={message.content} />;

    case 'ORDER_CANCELLED':
      return (
        <OrderCancelledCard metadata={metadata} content={message.content} />
      );

    case 'DELIVERY_DATE_CHANGE':
      return (
        <DeliveryDateChangeCard
          message={message}
          metadata={metadata}
          isMine={isMine}
        />
      );

    case 'DELIVERY_DATE_ACCEPTED':
      return (
        <DeliveryDateAcceptedCard metadata={metadata} content={message.content} />
      );

    case 'DELIVERY_DATE_REJECTED':
      return (
        <DeliveryDateRejectedCard metadata={metadata} content={message.content} />
      );

    case 'TEXT':
    default: {
      // US-2: 본인 발신 + draft_negotiation 존재 + 미dismiss 면 협상 감지 카드 렌더.
      // 백엔드도 막지만 프론트도 isMine 가드 (상대 메시지엔 절대 표시 안 함).
      const draft = metadata.draft_negotiation;
      const showDraftCard =
        isMine &&
        !!draft &&
        !draft.dismissed_at &&
        !!onAcceptNegotiationDraft &&
        !!onDismissNegotiationDraft;

      return (
        <div className="space-y-1">
          <TextBubble content={message.content} isMine={isMine} />
          {showDraftCard &&
            draft &&
            onAcceptNegotiationDraft &&
            onDismissNegotiationDraft && (
              <NegotiationDraftCard
                messageId={message.id}
                draft={draft}
                onAccept={onAcceptNegotiationDraft}
                onDismiss={onDismissNegotiationDraft}
                isDismissing={isDismissingNegotiationDraft}
              />
            )}
        </div>
      );
    }
  }
}

// ─── DELIVERY_DATE_ACCEPTED ────────────────────────────────────────

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

function DeliveryDateAcceptedCard({
  metadata,
  content,
}: {
  metadata: MessageMetadata;
  content: string;
}) {
  const accepted =
    metadata.accepted_delivery_date ?? metadata.proposed_delivery_date;
  return (
    <div className="flex justify-center">
      <div className="w-full max-w-[85%] rounded-xl border border-green-300 bg-green-50 p-3">
        <div className="flex items-center gap-2">
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-green-200 text-green-800">
            <Check className="h-3.5 w-3.5" />
          </span>
          <p className="text-sm font-medium text-green-900">
            납품일이 {formatDate(accepted)} 로 변경되었습니다
          </p>
        </div>
        {content && (
          <p className="mt-1 text-[11px] text-green-800/80">{content}</p>
        )}
      </div>
    </div>
  );
}

// ─── DELIVERY_DATE_REJECTED ────────────────────────────────────────

function DeliveryDateRejectedCard({
  metadata,
  content,
}: {
  metadata: MessageMetadata;
  content: string;
}) {
  const proposed = metadata.proposed_delivery_date;
  return (
    <div className="flex justify-center">
      <div className="w-full max-w-[85%] rounded-xl border border-gray-300 bg-gray-50 p-3">
        <div className="flex items-center gap-2">
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-gray-200 text-gray-700">
            <X className="h-3.5 w-3.5" />
          </span>
          <p className="text-sm font-medium text-gray-700">
            납품일 변경 거절
            {proposed && (
              <span className="ml-1 text-xs text-gray-500">
                ({formatDate(proposed)})
              </span>
            )}
          </p>
        </div>
        {content && (
          <p className="mt-1 text-[11px] text-gray-600">{content}</p>
        )}
      </div>
    </div>
  );
}

// ─── TEXT ───────────────────────────────────────────────────────────

function TextBubble({ content, isMine }: { content: string; isMine: boolean }) {
  return (
    <div className={cn('flex', isMine ? 'justify-end' : 'justify-start')}>
      <div
        className={cn(
          'max-w-[75%] whitespace-pre-wrap break-words rounded-2xl px-4 py-2 text-sm',
          isMine ? 'bg-primary-600 text-white' : 'bg-gray-100 text-gray-900'
        )}
      >
        {content}
      </div>
    </div>
  );
}

// ─── SYSTEM ─────────────────────────────────────────────────────────

function SystemNotice({
  content,
  metadata,
}: {
  content: string;
  metadata: MessageMetadata;
}) {
  // 백엔드 chat_service.send_event_message 가 SYSTEM 타입에 [SYSTEM] prefix 자동 부착함
  // → 프론트 노출 시 prefix 제거하여 깔끔하게 보여준다
  const cleaned = content.replace(/^\[SYSTEM\]\s*/, '');
  const orderNumber = metadata?.order_number;
  const totalAmount = metadata?.total_amount;

  return (
    <div className="flex justify-center">
      <div className="max-w-[90%] rounded-lg bg-gray-100 px-4 py-2 text-center text-xs text-gray-600">
        <p className="whitespace-pre-wrap">{cleaned}</p>
        {(orderNumber || typeof totalAmount === 'number') && (
          <p className="mt-1 text-[10px] text-gray-500">
            {orderNumber && <span>{orderNumber}</span>}
            {orderNumber && typeof totalAmount === 'number' && <span> · </span>}
            {typeof totalAmount === 'number' && (
              <span>{formatAmount(totalAmount)}</span>
            )}
          </p>
        )}
      </div>
    </div>
  );
}

// ─── COUNTER_OFFER ─────────────────────────────────────────────────

function CounterOfferCard({
  message,
  metadata,
  isMine,
}: {
  message: Message;
  metadata: MessageMetadata;
  isMine: boolean;
}) {
  const offerId = metadata.offer_id;
  const orderId = metadata.order_id;
  const proposedAmount = metadata.proposed_total_amount;
  const fromRole = metadata.from_role;
  const offerStatus = metadata.status ?? 'PENDING';
  const notes = metadata.notes;

  const acceptMutation = useAcceptCounterOffer(orderId ?? '');
  const rejectMutation = useRejectCounterOffer(orderId ?? '');

  const canAct =
    !isMine && offerStatus === 'PENDING' && !!offerId && !!orderId;

  const handleAccept = () => {
    if (!offerId || !orderId) return;
    // race condition 가드 — 카드 stale 상태면 버튼 클릭 무시 (PENDING 만 처리)
    if (offerStatus !== 'PENDING') return;
    acceptMutation.mutate({ offerId });
  };

  const handleReject = () => {
    if (!offerId || !orderId) return;
    if (offerStatus !== 'PENDING') return;
    rejectMutation.mutate({ offerId });
  };

  const statusBadge = (() => {
    switch (offerStatus) {
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
          'border-amber-300 bg-amber-50'
        )}
      >
        <div className="mb-2 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-amber-100 text-amber-700">
              <DollarSign className="h-4 w-4" />
            </span>
            <span className="text-xs font-semibold text-amber-900">
              {fromRole ? ROLE_LABEL[fromRole] : '상대방'}이(가) 새 협상가
              제시
            </span>
          </div>
          {statusBadge}
        </div>

        <div className="mb-2">
          <p className="text-2xl font-bold text-gray-900">
            {formatAmount(proposedAmount)}
          </p>
        </div>

        {notes && (
          <p className="mb-2 whitespace-pre-wrap break-words rounded-md bg-white/60 p-2 text-xs text-gray-700">
            {notes}
          </p>
        )}

        <div className="text-[10px] text-gray-500">{message.content}</div>

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
        {isMine && offerStatus === 'PENDING' && (
          <p className="mt-2 text-right text-[11px] text-gray-500">
            상대방 응답 대기 중
          </p>
        )}
      </div>
    </div>
  );
}

// ─── OFFER_ACCEPTED ────────────────────────────────────────────────

function OfferAcceptedCard({
  metadata,
  content,
}: {
  metadata: MessageMetadata;
  content: string;
}) {
  const accepted = metadata.accepted_amount ?? metadata.proposed_total_amount;
  return (
    <div className="flex justify-center">
      <div className="w-full max-w-[85%] rounded-xl border border-green-300 bg-green-50 p-3">
        <div className="flex items-center gap-2">
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-green-200 text-green-800">
            <Check className="h-3.5 w-3.5" />
          </span>
          <p className="text-sm font-medium text-green-900">
            {formatAmount(accepted)}에 협상 수락
          </p>
        </div>
        {content && (
          <p className="mt-1 text-[11px] text-green-800/80">{content}</p>
        )}
      </div>
    </div>
  );
}

// ─── OFFER_REJECTED ────────────────────────────────────────────────

function OfferRejectedCard({ content }: { content: string }) {
  return (
    <div className="flex justify-center">
      <div className="w-full max-w-[85%] rounded-xl border border-gray-300 bg-gray-50 p-3">
        <div className="flex items-center gap-2">
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-gray-200 text-gray-700">
            <X className="h-3.5 w-3.5" />
          </span>
          <p className="text-sm font-medium text-gray-700">협상가 거절</p>
        </div>
        {content && (
          <p className="mt-1 text-[11px] text-gray-600">{content}</p>
        )}
      </div>
    </div>
  );
}

// ─── ORDER_STATUS ──────────────────────────────────────────────────

function OrderStatusCard({
  metadata,
  content,
}: {
  metadata: MessageMetadata;
  content: string;
}) {
  const fromStatus = metadata.from_status;
  const toStatus = metadata.to_status;
  return (
    <div className="flex justify-center">
      <div className="w-full max-w-[90%] rounded-lg border border-blue-200 bg-blue-50 p-3">
        <div className="mb-1 flex items-center justify-center gap-1.5">
          <Package className="h-4 w-4 text-blue-600" />
          <span className="text-xs font-medium text-blue-900">
            주문 상태 변경
          </span>
        </div>
        <div className="flex items-center justify-center gap-2 text-xs">
          {fromStatus && <StatusBadge status={fromStatus} />}
          {fromStatus && toStatus && (
            <span className="text-gray-400">→</span>
          )}
          {toStatus && <StatusBadge status={toStatus} />}
        </div>
        {!fromStatus && !toStatus && content && (
          <p className="mt-1 text-center text-[11px] text-blue-800">
            {content}
          </p>
        )}
      </div>
    </div>
  );
}

// ─── ORDER_CANCELLED ───────────────────────────────────────────────

function OrderCancelledCard({
  metadata,
  content,
}: {
  metadata: MessageMetadata;
  content: string;
}) {
  const reason = metadata.reason;
  return (
    <div className="flex justify-center">
      <div className="w-full max-w-[85%] rounded-xl border border-red-300 bg-red-50 p-3">
        <div className="mb-1 flex items-center gap-2">
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-red-200 text-red-800">
            <Ban className="h-3.5 w-3.5" />
          </span>
          <p className="text-sm font-medium text-red-900">주문이 취소됐습니다</p>
        </div>
        {reason ? (
          <p className="whitespace-pre-wrap text-xs text-red-800">
            취소 사유: {reason}
          </p>
        ) : (
          content && (
            <p className="whitespace-pre-wrap text-xs text-red-800">{content}</p>
          )
        )}
      </div>
    </div>
  );
}
