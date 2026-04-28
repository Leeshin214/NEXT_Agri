'use client';

import { useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { MessageCircle, PackageCheck } from 'lucide-react';
import PageHeader from '@/components/common/PageHeader';
import DataTable, { type Column } from '@/components/common/DataTable';
import StatusBadge from '@/components/common/StatusBadge';
import NegotiationHistory from '@/components/common/NegotiationHistory';
import CancelOrderModal from '@/components/common/CancelOrderModal';
import PartnerDetailModal from '@/components/partners/PartnerDetailModal';
import CounterOfferModal from '@/components/seller/CounterOfferModal';
import {
  useNegotiationHistory,
  useOrder,
  useOrders,
  useUpdateOrderStatus,
} from '@/hooks/useOrders';
import {
  useAcceptSubscription,
  useGenerateSubscriptionOrder,
  useRejectSubscription,
  useSubscriptions,
} from '@/hooks/useSubscriptions';
import { usePartners } from '@/hooks/usePartners';
import { useCreateChatRoom } from '@/hooks/useChat';
import { useAuthStore } from '@/store/authStore';
import { ORDER_STATUS_OPTIONS } from '@/constants/options';
import { SUBSCRIPTION_STATUS_CONFIG } from '@/constants/status';
import type {
  CounterOffer,
  Order,
  OrderStatus,
  Partner,
  Subscription,
  SubscriptionFrequency,
  SubscriptionStatus,
} from '@/types';
import { cn } from '@/lib/utils';

interface TabDef {
  key: string;
  label: string;
  /** 일반 주문 탭이면 statuses, 정기배송 탭이면 isSubscription=true */
  statuses?: OrderStatus[];
  isSubscription?: boolean;
}

const tabs: TabDef[] = [
  {
    key: 'pending',
    label: '견적/진행',
    statuses: [
      'QUOTE_REQUESTED',
      'NEGOTIATING',
      'CONFIRMED',
      'PREPARING',
    ],
  },
  { key: 'shipping', label: '배송중', statuses: ['SHIPPING'] },
  { key: 'done', label: '완료/취소', statuses: ['COMPLETED', 'CANCELLED'] },
  { key: 'subscription', label: '정기배송', isSubscription: true },
];

const FREQUENCY_LABEL: Record<SubscriptionFrequency, string> = {
  WEEKLY: '매주',
  BIWEEKLY: '격주',
  MONTHLY: '매월',
};

/**
 * 판매자가 직접 보낼 수 있는 다음 상태.
 * CONFIRMED 전환은 buyer 만 가능 (백엔드 가드) → 판매자 UI에 노출하지 않음.
 */
const sellerNextStatusMap: Record<string, OrderStatus> = {
  CONFIRMED: 'PREPARING',
  PREPARING: 'SHIPPING',
  SHIPPING: 'COMPLETED',
};

const cancellableStatuses: OrderStatus[] = [
  'QUOTE_REQUESTED',
  'NEGOTIATING',
  'CONFIRMED',
  'PREPARING',
  'SHIPPING',
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

export default function SellerOrdersPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user } = useAuthStore();
  const currentUserId = user?.id ?? '';
  const [activeTab, setActiveTab] = useState('pending');
  const [selectedOrderId, setSelectedOrderId] = useState<string | null>(null);
  const [selectedPartner, setSelectedPartner] = useState<Partner | null>(null);

  const [showCancel, setShowCancel] = useState(false);
  const [showCounter, setShowCounter] = useState(false);

  const activeTabDef = tabs.find((t) => t.key === activeTab);
  const isSubTab = !!activeTabDef?.isSubscription;
  const activeStatuses = activeTabDef?.statuses ?? [];

  // 일반 주문: 탭별로 백엔드에서 status_in 다중 필터로 받아옴
  // 정기배송 탭이면 useOrders 비활성 (enabled false)
  const { data: listData, isLoading } = useOrders({
    status_in: isSubTab ? [] : activeStatuses,
    limit: 2000,
  });
  const filteredOrders = isSubTab ? [] : listData?.data ?? [];

  // 정기배송 탭에서만 useSubscriptions 호출 (비활성 탭에서는 enabled: false 로 fetch 차단)
  const subsData = useSubscriptions({ limit: 2000 }, { enabled: isSubTab });
  const allSubs: Subscription[] = isSubTab ? subsData.data?.data ?? [] : [];

  // 정기배송 탭의 거래처 매핑 — 행 클릭 시 PartnerDetailModal 오픈용
  const partnersData = usePartners();
  const partners: Partner[] = partnersData.data?.data ?? [];

  const { data: detailData } = useOrder(selectedOrderId ?? '');
  const selectedOrder: Order | null =
    detailData?.data ??
    (selectedOrderId
      ? filteredOrders.find((o) => o.id === selectedOrderId) ?? null
      : null);

  const updateStatus = useUpdateOrderStatus();
  const createChatRoom = useCreateChatRoom();

  // 정기배송 액션 mutation들
  const acceptSubscription = useAcceptSubscription();
  const rejectSubscription = useRejectSubscription();
  const generateOrder = useGenerateSubscriptionOrder();

  // 협상 이력 — 가장 최근 행이 ACCEPTED 면 협상가 제시 버튼 비활성화
  const { data: negotiationData } = useNegotiationHistory(selectedOrderId ?? '');
  const negotiationLatest: CounterOffer | null = (() => {
    const list = negotiationData?.data ?? [];
    if (list.length === 0) return null;
    return [...list].sort(
      (a, b) =>
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    )[0];
  })();
  const isNegotiationAccepted = negotiationLatest?.status === 'ACCEPTED';

  // 채팅 페이지에서 "주문 상세 보기" 클릭 시 ?id=... 쿼리스트링으로 진입 가능
  useEffect(() => {
    const idParam = searchParams.get('id');
    if (idParam) setSelectedOrderId(idParam);
  }, [searchParams]);

  const handleOpenChat = async () => {
    if (!selectedOrder) return;
    try {
      const res = await createChatRoom.mutateAsync({
        partner_user_id: selectedOrder.buyer_id,
        order_id: selectedOrder.id,
      });
      router.push(`/seller/chat?room_id=${res.data.id}`);
    } catch (e) {
      console.error('[seller/orders] 채팅방 생성 실패:', e);
    }
  };

  const handleNextStatus = (order: Order) => {
    const next = sellerNextStatusMap[order.status];
    if (next) updateStatus.mutate({ id: order.id, status: next });
  };

  const closeDetail = () => {
    setSelectedOrderId(null);
    setShowCancel(false);
    setShowCounter(false);
  };

  // 정기배송 행 클릭 — 거래처 모달로 점프 (해당 거래처의 정기배송 섹션)
  const handleSubRowClick = (sub: Subscription) => {
    const counterpartUserId =
      sub.seller_id === currentUserId ? sub.buyer_id : sub.seller_id;
    const partner = partners.find(
      (p) => p.partner_user_id === counterpartUserId
    );
    if (partner) {
      setSelectedPartner(partner);
    } else {
      // 거래처가 없으면 상세 정보를 alert 로
      alert('이 정기배송에 연결된 거래처가 없습니다.');
    }
  };

  const columns: Column<Order>[] = [
    {
      key: 'product',
      header: '상품',
      render: (item) => {
        const firstName = item.items?.[0]?.product_name ?? '상품 정보 없음';
        const extra =
          item.items.length > 1 ? ` 외 ${item.items.length - 1}건` : '';
        return (
          <div className="flex flex-col">
            <div className="flex items-center gap-1.5">
              <span className="font-medium text-gray-900">
                {firstName}
                {extra}
              </span>
              {item.subscription_id && (
                <span className="inline-flex flex-shrink-0 items-center rounded-full bg-purple-500 px-1.5 py-0.5 text-[10px] font-medium text-white">
                  정기 {item.subscription_round ?? '?'}회차
                </span>
              )}
            </div>
            <span className="text-xs text-gray-500">{item.order_number}</span>
          </div>
        );
      },
    },
    {
      key: 'buyer',
      header: '구매자',
      render: (item) => (
        <div className="flex flex-col">
          <span className="text-sm text-gray-900">
            {item.buyer_name ?? '-'}
          </span>
          {item.buyer_company && (
            <span className="text-xs text-gray-500">
              {item.buyer_company}
            </span>
          )}
        </div>
      ),
    },
    {
      key: 'total_amount',
      header: '금액',
      render: (item) => (
        <span className="text-gray-900">
          {item.total_amount
            ? `${item.total_amount.toLocaleString('ko-KR')}원`
            : '-'}
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
        const next = sellerNextStatusMap[item.status];
        if (!next) return null;
        const nextLabel = ORDER_STATUS_OPTIONS.find(
          (o) => o.value === next
        )?.label;
        return (
          <button
            onClick={(e) => {
              e.stopPropagation();
              handleNextStatus(item);
            }}
            className="rounded-lg bg-primary-50 px-3 py-1 text-xs font-medium text-primary-700 hover:bg-primary-100"
          >
            {nextLabel} 처리
          </button>
        );
      },
    },
  ];

  // 정기배송 탭 컬럼 정의
  const subscriptionColumns: Column<Subscription>[] = [
    {
      key: 'product',
      header: '상품',
      render: (sub) => {
        const firstName = sub.items?.[0]?.product_name ?? '상품 정보 없음';
        const extra =
          sub.items.length > 1 ? ` 외 ${sub.items.length - 1}건` : '';
        return (
          <div className="flex flex-col">
            <span className="font-medium text-gray-900">
              {firstName}
              {extra}
            </span>
          </div>
        );
      },
    },
    {
      key: 'partner',
      header: '구매자',
      render: (sub) => (
        <div className="flex flex-col">
          <span className="text-sm text-gray-900">
            {sub.buyer_name ?? '-'}
          </span>
          {sub.buyer_company && (
            <span className="text-xs text-gray-500">{sub.buyer_company}</span>
          )}
        </div>
      ),
    },
    {
      key: 'frequency',
      header: '주기',
      render: (sub) => (
        <span className="text-sm text-gray-700">
          {FREQUENCY_LABEL[sub.frequency]}
        </span>
      ),
    },
    {
      key: 'next',
      header: '다음 배송일',
      render: (sub) => (
        <span className="text-sm text-gray-700">
          {formatDate(sub.next_delivery_date)}
        </span>
      ),
    },
    {
      key: 'amount',
      header: '회당 금액',
      render: (sub) => (
        <span className="text-sm text-gray-900">
          {sub.total_amount.toLocaleString('ko-KR')}원
        </span>
      ),
    },
    {
      key: 'status',
      header: '상태',
      render: (sub) => {
        const cfg = SUBSCRIPTION_STATUS_CONFIG[
          sub.status as SubscriptionStatus
        ] ?? {
          label: sub.status,
          className: 'bg-gray-100 text-gray-600',
        };
        return (
          <span
            className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${cfg.className}`}
          >
            {cfg.label}
          </span>
        );
      },
    },
    {
      key: 'actions',
      header: '',
      className: 'text-right',
      render: (sub) => {
        const isMyRequest =
          sub.created_by === null || sub.created_by === currentUserId;
        // PENDING + 본인 created_by 가 아님 → 수락/거절
        if (sub.status === 'PENDING' && !isMyRequest) {
          return (
            <div
              className="flex items-center justify-end gap-1"
              onClick={(e) => e.stopPropagation()}
            >
              <button
                onClick={() => acceptSubscription.mutate(sub.id)}
                disabled={
                  acceptSubscription.isPending || rejectSubscription.isPending
                }
                className="rounded-lg bg-blue-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                수락
              </button>
              <button
                onClick={() => rejectSubscription.mutate(sub.id)}
                disabled={
                  acceptSubscription.isPending || rejectSubscription.isPending
                }
                className="rounded-lg border border-gray-300 bg-white px-2.5 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
              >
                거절
              </button>
            </div>
          );
        }
        if (sub.status === 'ACTIVE') {
          return (
            <button
              onClick={(e) => {
                e.stopPropagation();
                if (
                  window.confirm(
                    '이번 회차 주문을 즉시 생성하시겠습니까?\n주문/캘린더에 반영되며, 다음 회차 일정이 자동 진행됩니다.'
                  )
                ) {
                  generateOrder.mutate(sub.id);
                }
              }}
              disabled={generateOrder.isPending}
              className="inline-flex items-center gap-1 rounded-lg bg-primary-50 px-3 py-1 text-xs font-medium text-primary-700 hover:bg-primary-100 disabled:opacity-50"
            >
              <PackageCheck className="h-3.5 w-3.5" />
              회차 생성
            </button>
          );
        }
        return null;
      },
    },
  ];

  const detailNextStatus = selectedOrder
    ? sellerNextStatusMap[selectedOrder.status]
    : undefined;
  const detailNextLabel = detailNextStatus
    ? ORDER_STATUS_OPTIONS.find((o) => o.value === detailNextStatus)?.label
    : undefined;

  return (
    <div>
      <PageHeader
        title="주문/견적 관리"
        description="받은 견적 요청 및 주문을 관리하세요"
      />

      {/* 탭 — 활성 탭만 (N) 카운트 표시. 비활성 탭의 카운트는 서버 한 번에 알 수 없어 노출하지 않음 */}
      <div className="mb-4 flex gap-1 rounded-lg bg-gray-100 p-1">
        {tabs.map((tab) => {
          const isActive = activeTab === tab.key;
          const count = isActive
            ? tab.isSubscription
              ? allSubs.length
              : filteredOrders.length
            : null;
          return (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={cn(
                'flex-1 rounded-md px-4 py-2 text-sm font-medium transition-colors',
                isActive
                  ? 'bg-white text-gray-900 shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              )}
            >
              {tab.label}
              {count !== null ? ` (${count})` : ''}
            </button>
          );
        })}
      </div>

      {isSubTab ? (
        // 정기배송 탭
        subsData.isLoading ? (
          <div className="py-12 text-center text-sm text-gray-400">로딩 중...</div>
        ) : (
          <div className="max-h-[calc(100vh-280px)] overflow-y-auto rounded-xl">
            <DataTable
              columns={subscriptionColumns}
              data={allSubs}
              onRowClick={handleSubRowClick}
              emptyMessage="등록된 정기배송이 없습니다. 거래처 상세에서 새 정기배송을 등록하세요."
            />
          </div>
        )
      ) : isLoading ? (
        <div className="py-12 text-center text-sm text-gray-400">로딩 중...</div>
      ) : (
        <div className="max-h-[calc(100vh-280px)] overflow-y-auto rounded-xl">
          <DataTable
            columns={columns}
            data={filteredOrders}
            onRowClick={(o) => setSelectedOrderId(o.id)}
            emptyMessage="해당 상태의 주문이 없습니다."
          />
        </div>
      )}

      {/* 주문 상세 슬라이드 패널 */}
      {selectedOrder && (
        <div className="fixed inset-y-0 right-0 z-40 w-full bg-white shadow-xl sm:w-[420px]">
          <div className="flex h-full flex-col">
            <div className="flex items-start justify-between border-b border-gray-200 px-6 py-4">
              <div className="min-w-0 flex-1 pr-3">
                {(() => {
                  const firstItem = selectedOrder.items?.[0];
                  const firstName =
                    firstItem?.product_name ?? '상품 정보 없음';
                  const qtyUnit = firstItem
                    ? ` ${firstItem.quantity}${
                        firstItem.product_unit ?? ''
                      }`
                    : '';
                  const extra =
                    selectedOrder.items.length > 1
                      ? ` 외 ${selectedOrder.items.length - 1}건`
                      : '';
                  return (
                    <h2 className="truncate text-lg font-semibold text-gray-900">
                      {firstName}
                      {qtyUnit}
                      {extra}
                    </h2>
                  );
                })()}
                <p className="mt-0.5 truncate text-xs text-gray-500">
                  {selectedOrder.order_number}
                </p>
                {selectedOrder.subscription_id && (
                  <p className="mt-1 inline-flex items-center rounded-full bg-purple-500 px-2 py-0.5 text-[10px] font-medium text-white">
                    정기배송 {selectedOrder.subscription_round ?? '?'}회차
                  </p>
                )}
                <p className="mt-1 truncate text-xs text-gray-600">
                  구매자: {selectedOrder.buyer_name ?? '-'}
                  {selectedOrder.buyer_company
                    ? ` (${selectedOrder.buyer_company})`
                    : ''}
                </p>
              </div>
              <button
                onClick={closeDetail}
                className="flex-shrink-0 text-gray-400 hover:text-gray-600"
              >
                닫기
              </button>
            </div>
            <div className="flex-1 space-y-4 overflow-y-auto p-6">
              <div>
                <p className="text-xs text-gray-500">상태</p>
                <StatusBadge status={selectedOrder.status} />
              </div>
              <div>
                <p className="text-xs text-gray-500">총 금액</p>
                <p className="text-lg font-semibold text-gray-900">
                  {selectedOrder.total_amount
                    ? `${selectedOrder.total_amount.toLocaleString('ko-KR')}원`
                    : '-'}
                </p>
              </div>
              <div>
                <p className="text-xs text-gray-500">납품일</p>
                <p className="text-sm text-gray-900">
                  {selectedOrder.delivery_date || '미정'}
                </p>
              </div>
              {selectedOrder.delivery_address && (
                <div>
                  <p className="text-xs text-gray-500">배송지</p>
                  <p className="whitespace-pre-wrap text-sm text-gray-900">
                    {selectedOrder.delivery_address}
                  </p>
                </div>
              )}
              {selectedOrder.notes && (
                <div>
                  <p className="text-xs text-gray-500">메모</p>
                  <p className="whitespace-pre-wrap text-sm text-gray-900">
                    {selectedOrder.notes}
                  </p>
                </div>
              )}

              {/* 취소 정보 */}
              {selectedOrder.status === 'CANCELLED' && (
                <div className="rounded-lg border border-red-200 bg-red-50 p-3">
                  <p className="mb-1 text-xs font-medium text-red-700">
                    취소됨
                  </p>
                  {selectedOrder.cancellation_reason && (
                    <p className="whitespace-pre-wrap text-sm text-red-800">
                      {selectedOrder.cancellation_reason}
                    </p>
                  )}
                  {selectedOrder.cancelled_at && (
                    <p className="mt-1 text-[10px] text-red-600">
                      {formatDateTime(selectedOrder.cancelled_at)}
                    </p>
                  )}
                </div>
              )}

              {selectedOrder.items.length > 0 && (
                <div>
                  <p className="mb-2 text-xs text-gray-500">주문 항목</p>
                  <div className="space-y-2">
                    {selectedOrder.items.map((item) => (
                      <div
                        key={item.id}
                        className="rounded-lg bg-gray-50 p-3 text-sm"
                      >
                        <p className="mb-1 font-medium text-gray-900">
                          {item.product_name ?? '상품 정보 없음'}
                        </p>
                        <div className="flex justify-between">
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
                          <p className="mt-1 text-xs text-gray-500">
                            {item.notes}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* 협상 이력 */}
              <NegotiationHistory
                orderId={selectedOrder.id}
                orderStatus={selectedOrder.status}
              />
            </div>

            {/* 액션 버튼 영역 */}
            <div className="border-t border-gray-200 p-4">
              <div className="flex flex-wrap gap-2">
                {selectedOrder.status !== 'CANCELLED' && (
                  <button
                    onClick={handleOpenChat}
                    disabled={createChatRoom.isPending}
                    className="inline-flex items-center gap-1 rounded-lg border border-primary-600 bg-white px-3 py-2 text-xs font-medium text-primary-700 hover:bg-primary-50 disabled:opacity-50"
                  >
                    <MessageCircle className="h-3.5 w-3.5" />
                    채팅으로 대화
                  </button>
                )}
                {detailNextStatus && (
                  <button
                    onClick={() => handleNextStatus(selectedOrder)}
                    disabled={updateStatus.isPending}
                    className="rounded-lg bg-primary-600 px-3 py-2 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50"
                  >
                    {detailNextLabel} 처리
                  </button>
                )}
                {counterOfferableStatuses.includes(selectedOrder.status) && (
                  <button
                    onClick={() =>
                      updateStatus.mutate({
                        id: selectedOrder.id,
                        status: 'CONFIRMED',
                      })
                    }
                    disabled={updateStatus.isPending}
                    className="rounded-lg bg-primary-600 px-3 py-2 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50"
                  >
                    주문 확정
                  </button>
                )}
                {counterOfferableStatuses.includes(selectedOrder.status) && (
                  <button
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
                {cancellableStatuses.includes(selectedOrder.status) && (
                  <button
                    onClick={() => setShowCancel(true)}
                    className="rounded-lg border border-red-300 bg-white px-3 py-2 text-xs font-medium text-red-600 hover:bg-red-50"
                  >
                    취소
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 모달들 */}
      {selectedOrder && (
        <>
          <CancelOrderModal
            isOpen={showCancel}
            onClose={() => setShowCancel(false)}
            orderId={selectedOrder.id}
            orderNumber={selectedOrder.order_number}
          />
          <CounterOfferModal
            isOpen={showCounter}
            onClose={() => setShowCounter(false)}
            orderId={selectedOrder.id}
            orderNumber={selectedOrder.order_number}
            currentTotal={selectedOrder.total_amount}
          />
        </>
      )}

      {/* 정기배송 행 클릭 → 거래처 상세 모달 */}
      <PartnerDetailModal
        partner={selectedPartner}
        myRole="SELLER"
        onClose={() => setSelectedPartner(null)}
      />
    </div>
  );
}
