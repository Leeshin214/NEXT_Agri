'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { ArrowLeft, MessageCircle } from 'lucide-react';
import StatusBadge from '@/components/common/StatusBadge';
import NegotiationHistory from '@/components/common/NegotiationHistory';
import DeliveryDateChangeSection from '@/components/common/DeliveryDateChangeSection';
import CancelOrderModal from '@/components/common/CancelOrderModal';
import CancelRequestModal from '@/components/common/CancelRequestModal';
import CancelRequestPanel from '@/components/common/CancelRequestPanel';
import EditOrderModal from '@/components/buyer/EditOrderModal';
import CounterOfferModal from '@/components/seller/CounterOfferModal';
import {
  useNegotiationHistory,
  useOrder,
  useUpdateOrderStatus,
} from '@/hooks/useOrders';
import { useCreateChatRoom } from '@/hooks/useChat';
import { ORDER_STATUS_OPTIONS } from '@/constants/options';
import type { CounterOffer, Order, OrderStatus, UserRole } from '@/types';

interface OrderDetailViewProps {
  orderId: string;
  myRole: UserRole;
}

/**
 * 판매자가 직접 보낼 수 있는 다음 상태 (CONFIRMED → buyer 만 가능).
 * 양쪽 페이지에서 동일하게 사용되는 매핑.
 */
const sellerNextStatusMap: Record<string, OrderStatus> = {
  CONFIRMED: 'PREPARING',
  PREPARING: 'SHIPPING',
  SHIPPING: 'COMPLETED',
};

const cancellableStatusesSeller: OrderStatus[] = [
  'QUOTE_REQUESTED',
  'NEGOTIATING',
  'CONFIRMED',
  'PREPARING',
  'SHIPPING',
];

const buyerDirectCancelStatuses: OrderStatus[] = [
  'QUOTE_REQUESTED',
  'NEGOTIATING',
];

const counterOfferableStatuses: OrderStatus[] = [
  'QUOTE_REQUESTED',
  'NEGOTIATING',
];

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '-';
  try {
    return new Date(iso).toLocaleString('ko-KR', {
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

/**
 * 주문 상세 뷰 — `/buyer/orders/[id]` 와 `/seller/orders/[id]` 양쪽에서 공통 사용.
 *
 * 설계 원칙:
 * - 데이터 fetching 은 useOrder/useNegotiationHistory 훅으로 일임 → 캐시 자동 공유
 * - 액션은 상태 + myRole 조합에 따라 노출 (목록 페이지 슬라이드 패널과 동일 규칙)
 * - 권한 없거나 존재하지 않는 주문은 "주문을 찾을 수 없습니다" 화면 (백엔드 403/404 동일 처리)
 * - 협상 이력 / 납품일 변경 섹션은 기존 공통 컴포넌트 재사용
 * - 모바일: 그리드 → 컬럼 스택 (Tailwind sm: 기준)
 */
export default function OrderDetailView({
  orderId,
  myRole,
}: OrderDetailViewProps) {
  const router = useRouter();
  const isBuyer = myRole === 'BUYER';
  const roleSlug = isBuyer ? 'buyer' : 'seller';

  const [showEdit, setShowEdit] = useState(false);
  const [showCancel, setShowCancel] = useState(false);
  const [showCancelRequest, setShowCancelRequest] = useState(false);
  const [showCounter, setShowCounter] = useState(false);

  const { data, isLoading, error } = useOrder(orderId);
  const order: Order | null = data?.data ?? null;

  const { data: negotiationData } = useNegotiationHistory(
    order ? order.id : ''
  );
  const negotiationLatest: CounterOffer | null = (() => {
    const list = negotiationData?.data ?? [];
    if (list.length === 0) return null;
    return [...list].sort(
      (a, b) =>
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    )[0];
  })();
  const isNegotiationAccepted = negotiationLatest?.status === 'ACCEPTED';

  const updateStatus = useUpdateOrderStatus();
  const createChatRoom = useCreateChatRoom();

  const handleOpenChat = async () => {
    if (!order) return;
    try {
      const partnerUserId = isBuyer ? order.seller_id : order.buyer_id;
      const res = await createChatRoom.mutateAsync({
        partner_user_id: partnerUserId,
        order_id: order.id,
      });
      router.push(`/${roleSlug}/chat?room_id=${res.data.id}`);
    } catch (e) {
      console.error('[OrderDetailView] 채팅방 생성 실패:', e);
    }
  };

  const handleNextStatus = () => {
    if (!order) return;
    const next = sellerNextStatusMap[order.status];
    if (next) updateStatus.mutate({ id: order.id, status: next });
  };

  const handleBack = () => {
    // 직접 URL 진입 케이스 대비 — history 가 없으면 목록으로 fallback
    if (typeof window !== 'undefined' && window.history.length > 1) {
      router.back();
    } else {
      router.push(`/${roleSlug}/orders`);
    }
  };

  // ─── 로딩 ─────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="py-12 text-center text-sm text-gray-500">
        불러오는 중...
      </div>
    );
  }

  // ─── 에러 / 권한 없음 / 미존재 ──────────────────────────────────
  if (error || !order) {
    return (
      <div className="mx-auto max-w-md py-16 text-center">
        <h2 className="text-lg font-semibold text-gray-900">
          주문을 찾을 수 없습니다
        </h2>
        <p className="mt-2 text-sm text-gray-500">
          삭제되었거나 접근 권한이 없는 주문일 수 있습니다.
        </p>
        <button
          type="button"
          onClick={() => router.push(`/${roleSlug}/orders`)}
          className="mt-6 inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          <ArrowLeft className="h-4 w-4" />
          주문 목록으로 돌아가기
        </button>
      </div>
    );
  }

  // ─── 본문 ─────────────────────────────────────────────────────
  const counterpartLabel = isBuyer ? '판매자' : '구매자';
  const counterpartName = isBuyer ? order.seller_name : order.buyer_name;
  const counterpartCompany = isBuyer
    ? order.seller_company
    : order.buyer_company;

  const detailNextStatus = !isBuyer ? sellerNextStatusMap[order.status] : null;
  const detailNextLabel = detailNextStatus
    ? ORDER_STATUS_OPTIONS.find((o) => o.value === detailNextStatus)?.label
    : null;

  const firstItem = order.items?.[0];
  const firstName = firstItem?.product_name ?? '상품 정보 없음';
  const qtyUnit = firstItem
    ? ` ${firstItem.quantity}${firstItem.product_unit ?? ''}`
    : '';
  const extra =
    order.items.length > 1 ? ` 외 ${order.items.length - 1}건` : '';

  return (
    <div className="space-y-6">
      {/* 헤더 — 뒤로가기 + 제목 + 상태 */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-2">
          <button
            type="button"
            onClick={handleBack}
            className="mt-0.5 inline-flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg border border-gray-200 bg-white text-gray-600 hover:bg-gray-50"
            aria-label="뒤로가기"
          >
            <ArrowLeft className="h-4 w-4" />
          </button>
          <div className="min-w-0">
            <h1 className="truncate text-xl font-semibold text-gray-900 sm:text-2xl">
              {firstName}
              {qtyUnit}
              {extra}
            </h1>
            <p className="mt-0.5 truncate text-xs text-gray-500">
              {order.order_number}
            </p>
            {order.subscription_id && (
              <span className="mt-2 inline-flex items-center rounded-full bg-purple-500 px-2 py-0.5 text-[10px] font-medium text-white">
                정기배송 {order.subscription_round ?? '?'}회차
              </span>
            )}
          </div>
        </div>
        <div className="flex flex-shrink-0 items-center gap-2">
          <StatusBadge status={order.status} />
          {order.pending_cancel_request && (
            <span className="inline-flex items-center rounded-full bg-orange-100 px-2 py-0.5 text-[10px] font-medium text-orange-700">
              취소 요청 대기중
            </span>
          )}
        </div>
      </div>

      {/* 기본 정보 카드 — sm 이상에서 2열 그리드, 미만은 1열 스택 */}
      <div className="grid grid-cols-1 gap-4 rounded-xl border border-gray-200 bg-white p-5 sm:grid-cols-2">
        <div>
          <p className="text-xs text-gray-500">{counterpartLabel}</p>
          <p className="mt-0.5 text-sm font-medium text-gray-900">
            {counterpartName ?? '-'}
          </p>
          {counterpartCompany && (
            <p className="text-xs text-gray-500">{counterpartCompany}</p>
          )}
        </div>
        <div>
          <p className="text-xs text-gray-500">총 금액</p>
          <p className="mt-0.5 text-lg font-semibold text-gray-900">
            {order.total_amount
              ? `${order.total_amount.toLocaleString('ko-KR')}원`
              : '-'}
          </p>
        </div>
        <div>
          <p className="text-xs text-gray-500">납품일</p>
          <p className="mt-0.5 text-sm text-gray-900">
            {order.delivery_date || '미정'}
          </p>
        </div>
        <div>
          <p className="text-xs text-gray-500">생성일</p>
          <p className="mt-0.5 text-sm text-gray-900">
            {formatDateTime(order.created_at)}
          </p>
        </div>
        {order.delivery_address && (
          <div className="sm:col-span-2">
            <p className="text-xs text-gray-500">배송지</p>
            <p className="mt-0.5 whitespace-pre-wrap text-sm text-gray-900">
              {order.delivery_address}
            </p>
          </div>
        )}
        {order.notes && (
          <div className="sm:col-span-2">
            <p className="text-xs text-gray-500">메모</p>
            <p className="mt-0.5 whitespace-pre-wrap text-sm text-gray-900">
              {order.notes}
            </p>
          </div>
        )}
      </div>

      {/* 취소 정보 */}
      {order.status === 'CANCELLED' && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4">
          <p className="mb-1 text-xs font-medium text-red-700">취소됨</p>
          {order.cancellation_reason && (
            <p className="whitespace-pre-wrap text-sm text-red-800">
              {order.cancellation_reason}
            </p>
          )}
          {order.cancelled_at && (
            <p className="mt-1 text-[10px] text-red-600">
              {formatDateTime(order.cancelled_at)}
            </p>
          )}
        </div>
      )}

      {/* 주문 항목 */}
      {order.items.length > 0 && (
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <h2 className="mb-3 text-sm font-semibold text-gray-900">주문 항목</h2>
          <div className="space-y-2">
            {order.items.map((item) => (
              <div
                key={item.id}
                className="rounded-lg bg-gray-50 p-3 text-sm"
              >
                <p className="mb-1 font-medium text-gray-900">
                  {item.product_name ?? '상품 정보 없음'}
                </p>
                <div className="flex flex-col gap-0.5 sm:flex-row sm:items-center sm:justify-between">
                  <span className="text-gray-700">
                    수량 {item.quantity}
                    {item.product_unit ? item.product_unit : ''} ×{' '}
                    {item.unit_price.toLocaleString('ko-KR')}원
                  </span>
                  <span className="font-medium text-gray-900">
                    {item.subtotal.toLocaleString('ko-KR')}원
                  </span>
                </div>
                {item.notes && (
                  <p className="mt-1 text-xs text-gray-500">{item.notes}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 협상 이력 */}
      <div className="rounded-xl border border-gray-200 bg-white p-5">
        <NegotiationHistory orderId={order.id} orderStatus={order.status} />
      </div>

      {/* 납품일 변경 */}
      <div className="rounded-xl border border-gray-200 bg-white p-5">
        <DeliveryDateChangeSection
          orderId={order.id}
          orderStatus={order.status}
          currentDeliveryDate={order.delivery_date}
        />
      </div>

      {/* 판매자 — 구매자 취소 요청 응답 패널 */}
      {!isBuyer && order.pending_cancel_request && (
        <CancelRequestPanel
          orderId={order.id}
          cancelRequest={order.pending_cancel_request}
        />
      )}

      {/* 액션 영역 */}
      <div className="rounded-xl border border-gray-200 bg-white p-5">
        {isBuyer && order.status === 'SHIPPING' && (
          <p className="mb-3 text-xs text-gray-500">
            물건을 받으셨다면 완료 처리해 주세요
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          {/* 채팅 (취소 제외 모든 상태) */}
          {order.status !== 'CANCELLED' && (
            <button
              type="button"
              onClick={handleOpenChat}
              disabled={createChatRoom.isPending}
              className="inline-flex items-center gap-1 rounded-lg border border-primary-600 bg-white px-3 py-2 text-xs font-medium text-primary-700 hover:bg-primary-50 disabled:opacity-50"
            >
              <MessageCircle className="h-3.5 w-3.5" />
              채팅으로 대화
            </button>
          )}

          {/* === 구매자 전용 액션 === */}
          {isBuyer && order.status === 'QUOTE_REQUESTED' && (
            <button
              type="button"
              onClick={() => setShowEdit(true)}
              className="rounded-lg border border-gray-300 px-3 py-2 text-xs font-medium hover:bg-gray-50"
            >
              수정
            </button>
          )}
          {isBuyer && order.status === 'SHIPPING' && (
            <button
              type="button"
              onClick={() =>
                updateStatus.mutate({
                  id: order.id,
                  status: 'COMPLETED',
                })
              }
              disabled={updateStatus.isPending}
              className="rounded-lg bg-primary-600 px-3 py-2 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50"
            >
              수령 완료
            </button>
          )}

          {/* === 판매자 전용 액션 === */}
          {!isBuyer && detailNextStatus && (
            <button
              type="button"
              onClick={handleNextStatus}
              disabled={updateStatus.isPending}
              className="rounded-lg bg-primary-600 px-3 py-2 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50"
            >
              {detailNextLabel} 처리
            </button>
          )}
          {!isBuyer && counterOfferableStatuses.includes(order.status) && (
            <button
              type="button"
              onClick={() =>
                updateStatus.mutate({
                  id: order.id,
                  status: 'CONFIRMED',
                })
              }
              disabled={updateStatus.isPending}
              className="rounded-lg bg-primary-600 px-3 py-2 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50"
            >
              주문 확정
            </button>
          )}

          {/* === 협상가 제시 (양쪽 공통, 단 NEGOTIATING/QUOTE_REQUESTED 시) === */}
          {counterOfferableStatuses.includes(order.status) && (
            <button
              type="button"
              onClick={() => setShowCounter(true)}
              disabled={isNegotiationAccepted}
              title={
                isNegotiationAccepted
                  ? '이미 협상이 수락되어 가격이 확정되었습니다. 주문 확정 버튼을 눌러주세요.'
                  : undefined
              }
              className="rounded-lg border border-primary-600 bg-white px-3 py-2 text-xs font-medium text-primary-700 hover:bg-primary-50 disabled:cursor-not-allowed disabled:border-gray-300 disabled:bg-gray-100 disabled:text-gray-400 disabled:hover:bg-gray-100"
            >
              협상가 제시
            </button>
          )}

          {/* === 취소 (구매자: QUOTE_REQUESTED/NEGOTIATING 직접 / CONFIRMED 요청) === */}
          {isBuyer && buyerDirectCancelStatuses.includes(order.status) && (
            <button
              type="button"
              onClick={() => setShowCancel(true)}
              className="rounded-lg border border-red-300 bg-white px-3 py-2 text-xs font-medium text-red-600 hover:bg-red-50"
            >
              취소
            </button>
          )}
          {isBuyer &&
            order.status === 'CONFIRMED' &&
            (order.pending_cancel_request ? (
              <span className="rounded-lg border border-orange-300 bg-orange-50 px-3 py-2 text-xs font-medium text-orange-700">
                취소 요청 대기중
              </span>
            ) : (
              <button
                type="button"
                onClick={() => setShowCancelRequest(true)}
                className="rounded-lg border border-orange-300 bg-white px-3 py-2 text-xs font-medium text-orange-700 hover:bg-orange-50"
              >
                취소 요청
              </button>
            ))}

          {/* 판매자: 광범위한 상태에서 직접 취소 가능 */}
          {!isBuyer && cancellableStatusesSeller.includes(order.status) && (
            <button
              type="button"
              onClick={() => setShowCancel(true)}
              className="rounded-lg border border-red-300 bg-white px-3 py-2 text-xs font-medium text-red-600 hover:bg-red-50"
            >
              취소
            </button>
          )}
        </div>
      </div>

      {/* 모달들 */}
      {isBuyer && (
        <EditOrderModal
          isOpen={showEdit}
          onClose={() => setShowEdit(false)}
          order={order}
        />
      )}
      <CancelOrderModal
        isOpen={showCancel}
        onClose={() => setShowCancel(false)}
        orderId={order.id}
        orderNumber={order.order_number}
      />
      {isBuyer && (
        <CancelRequestModal
          isOpen={showCancelRequest}
          onClose={() => setShowCancelRequest(false)}
          orderId={order.id}
          orderNumber={order.order_number}
        />
      )}
      <CounterOfferModal
        isOpen={showCounter}
        onClose={() => setShowCounter(false)}
        orderId={order.id}
        orderNumber={order.order_number}
        currentTotal={order.total_amount}
      />
    </div>
  );
}
