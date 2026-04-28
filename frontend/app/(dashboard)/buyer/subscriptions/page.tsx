'use client';

import { useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  ChevronDown,
  ChevronUp,
  ExternalLink,
  PackageCheck,
  Pause,
  Play,
  Trash2,
} from 'lucide-react';
import PageHeader from '@/components/common/PageHeader';
import PartnerDetailModal from '@/components/partners/PartnerDetailModal';
import {
  useAcceptSubscription,
  useDeleteSubscription,
  useGenerateSubscriptionOrder,
  useRejectSubscription,
  useSubscriptions,
  useUpdateSubscriptionGeneric,
} from '@/hooks/useSubscriptions';
import { usePartners } from '@/hooks/usePartners';
import { useAuthStore } from '@/store/authStore';
import { SUBSCRIPTION_STATUS_CONFIG } from '@/constants/status';
import type {
  Partner,
  Subscription,
  SubscriptionFrequency,
  SubscriptionStatus,
} from '@/types';
import { cn } from '@/lib/utils';

/**
 * 정기배송 관리 페이지 (V1.6 신규).
 *
 * - useSubscriptions 훅으로 본인이 buyer 또는 seller 인 정기배송을 모두 조회.
 * - 상태 필터 탭으로 분류 (전체 / 진행중 / 승인대기 / 일시정지 / 종료).
 * - 행 클릭 → 펼침. 펼침 영역에서 회차 생성/일시정지/재개/수락/거절/해지/거래처 점프 액션.
 * - 별도 SubscriptionDetailModal 이 없으므로 인라인 펼침으로 구현.
 *
 * seller / buyer 페이지는 byte-identical:
 *   - PAGE_ROLE: 'SELLER' | 'BUYER'  (myRole prop 으로 전달)
 *   - PARTNERS_ROUTE: 거래처 페이지 경로 (빈 상태에서 안내)
 *   - PAGE_DESCRIPTION: PageHeader 설명
 *   - COUNTERPART_LABEL: 상대방 호칭 (거래처/공급처)
 * 외 차이가 없도록 작성.
 */
const PAGE_ROLE: 'SELLER' | 'BUYER' = 'BUYER';
const PARTNERS_ROUTE = '/buyer/partners';
const PAGE_DESCRIPTION = '공급처별 정기배송을 관리하세요';
const COUNTERPART_LABEL = '판매자';

const FREQUENCY_LABEL: Record<SubscriptionFrequency, string> = {
  WEEKLY: '매주',
  BIWEEKLY: '격주',
  MONTHLY: '매월',
};

const DAY_OF_WEEK_LABEL: Record<number, string> = {
  0: '일요일',
  1: '월요일',
  2: '화요일',
  3: '수요일',
  4: '목요일',
  5: '금요일',
  6: '토요일',
};

interface FilterDef {
  key: string;
  label: string;
  /** 백엔드에 전달할 단일 status. undefined 이면 전체. */
  status?: SubscriptionStatus;
  /**
   * 클라이언트 사이드에서 추가 매칭할 status 집합 (status 가 undefined 일 때는 무시).
   * 종료 탭처럼 ENDED/CANCELLED/REJECTED 를 묶어서 보여줄 때 사용.
   */
  clientStatuses?: SubscriptionStatus[];
}

const filterTabs: FilterDef[] = [
  { key: 'all', label: '전체' },
  { key: 'active', label: '진행중', status: 'ACTIVE' },
  { key: 'pending', label: '승인 대기', status: 'PENDING' },
  { key: 'paused', label: '일시정지', status: 'PAUSED' },
  {
    key: 'ended',
    label: '종료',
    clientStatuses: ['ENDED', 'CANCELLED', 'REJECTED'],
  },
];

/** 정렬 우선순위 — 활성/대기 우선, 종료/취소/거절은 뒤로. */
const STATUS_PRIORITY: Record<SubscriptionStatus, number> = {
  ACTIVE: 0,
  PENDING: 1,
  PAUSED: 2,
  ENDED: 3,
  CANCELLED: 4,
  REJECTED: 5,
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

function formatScheduleLabel(sub: Subscription): string {
  const base = FREQUENCY_LABEL[sub.frequency];
  if (sub.frequency === 'MONTHLY') {
    return sub.day_of_month != null ? `${base} ${sub.day_of_month}일` : base;
  }
  if (sub.day_of_week != null) {
    return `${base} ${DAY_OF_WEEK_LABEL[sub.day_of_week] ?? ''}`.trim();
  }
  return base;
}

export default function SubscriptionsPage() {
  const router = useRouter();
  const { user } = useAuthStore();
  const currentUserId = user?.id ?? '';

  const [activeFilter, setActiveFilter] = useState<string>('all');
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [selectedPartner, setSelectedPartner] = useState<Partner | null>(null);

  const activeFilterDef = filterTabs.find((f) => f.key === activeFilter);

  // 백엔드 status 필터는 단일값만 지원 → "종료" 처럼 여러 status 묶음은 전체 fetch 후 클라이언트 필터.
  const useServerStatus =
    !!activeFilterDef?.status && !activeFilterDef.clientStatuses;

  const { data: listData, isLoading } = useSubscriptions({
    status: useServerStatus ? activeFilterDef!.status : undefined,
    limit: 2000,
  });

  const allSubs: Subscription[] = listData?.data ?? [];

  const filtered = useMemo(() => {
    let result = allSubs;
    if (activeFilterDef?.clientStatuses) {
      const set = new Set<SubscriptionStatus>(activeFilterDef.clientStatuses);
      result = result.filter((s) => set.has(s.status));
    } else if (!useServerStatus && activeFilterDef?.status) {
      // 안전장치 — 일반적으로 도달 불가 (useServerStatus 분기 처리됨)
      result = result.filter((s) => s.status === activeFilterDef.status);
    }
    return [...result].sort((a, b) => {
      const pa = STATUS_PRIORITY[a.status] ?? 99;
      const pb = STATUS_PRIORITY[b.status] ?? 99;
      if (pa !== pb) return pa - pb;
      // 동일 status 내에서는 next_delivery_date asc
      return (
        new Date(a.next_delivery_date).getTime() -
        new Date(b.next_delivery_date).getTime()
      );
    });
  }, [allSubs, activeFilterDef, useServerStatus]);

  // 거래처 매핑 — 정기배송 행에서 거래처 모달 점프용
  const partnersData = usePartners();
  const partners: Partner[] = partnersData.data?.data ?? [];

  // mutation 훅
  const acceptSubscription = useAcceptSubscription();
  const rejectSubscription = useRejectSubscription();
  const generateOrder = useGenerateSubscriptionOrder();
  const updateGeneric = useUpdateSubscriptionGeneric();
  const deleteSubscription = useDeleteSubscription();

  const handleToggleRow = (id: string) => {
    setExpandedId((prev) => (prev === id ? null : id));
  };

  const handleJumpToPartner = (sub: Subscription) => {
    const counterpartUserId =
      sub.seller_id === currentUserId ? sub.buyer_id : sub.seller_id;
    const partner = partners.find(
      (p) => p.partner_user_id === counterpartUserId
    );
    if (partner) {
      setSelectedPartner(partner);
    } else {
      router.push(PARTNERS_ROUTE);
    }
  };

  const handleGenerateOrder = (sub: Subscription) => {
    if (
      window.confirm(
        '이번 회차 주문을 즉시 생성하시겠습니까?\n주문/캘린더에 반영되며, 다음 회차 일정이 자동 진행됩니다.'
      )
    ) {
      generateOrder.mutate(sub.id);
    }
  };

  const handleTogglePause = (sub: Subscription) => {
    const next: SubscriptionStatus =
      sub.status === 'ACTIVE' ? 'PAUSED' : 'ACTIVE';
    updateGeneric.mutate({ id: sub.id, data: { status: next } });
  };

  const handleDelete = (sub: Subscription) => {
    if (
      window.confirm(
        '이 정기배송을 해지(취소)하시겠습니까?\n해지된 정기배송은 복구할 수 없습니다.'
      )
    ) {
      deleteSubscription.mutate(sub.id);
      if (expandedId === sub.id) setExpandedId(null);
    }
  };

  const isLoaded = !isLoading;
  const hasSubscriptions = allSubs.length > 0;

  return (
    <div>
      <PageHeader title="정기배송 관리" description={PAGE_DESCRIPTION} />

      {/* 상태 필터 탭 */}
      <div className="mb-4 flex flex-wrap gap-1 rounded-lg bg-gray-100 p-1">
        {filterTabs.map((tab) => {
          const isActive = activeFilter === tab.key;
          const count = isActive ? filtered.length : null;
          return (
            <button
              key={tab.key}
              onClick={() => {
                setActiveFilter(tab.key);
                setExpandedId(null);
              }}
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

      {/* 빈 상태 */}
      {isLoaded && !hasSubscriptions && (
        <div className="rounded-xl bg-white py-16 text-center shadow-sm">
          <p className="text-sm text-gray-500">
            등록된 정기배송이 없습니다. 거래처 페이지에서 정기배송을 등록할 수 있습니다.
          </p>
          <button
            onClick={() => router.push(PARTNERS_ROUTE)}
            className="mt-4 inline-flex items-center gap-1 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700"
          >
            거래처 페이지로 이동
            <ExternalLink className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* 로딩 */}
      {!isLoaded && (
        <div className="py-12 text-center text-sm text-gray-400">로딩 중...</div>
      )}

      {/* 필터 결과는 있는데 현재 필터에서는 0건 */}
      {isLoaded && hasSubscriptions && filtered.length === 0 && (
        <div className="rounded-xl bg-white py-12 text-center shadow-sm">
          <p className="text-sm text-gray-400">
            해당 상태의 정기배송이 없습니다.
          </p>
        </div>
      )}

      {/* 카드 리스트 */}
      {isLoaded && filtered.length > 0 && (
        <div className="space-y-2">
          {filtered.map((sub) => {
            const isExpanded = expandedId === sub.id;
            const cfg = SUBSCRIPTION_STATUS_CONFIG[sub.status] ?? {
              label: sub.status,
              className: 'bg-gray-100 text-gray-600',
            };
            const firstName =
              sub.items?.[0]?.product_name ?? '상품 정보 없음';
            const extra =
              sub.items.length > 1 ? ` 외 ${sub.items.length - 1}건` : '';

            // 상대방 정보 — 판매자 페이지에서는 buyer, 구매자 페이지에서는 seller 가 상대방.
            const counterpartName =
              PAGE_ROLE === 'SELLER' ? sub.buyer_name : sub.seller_name;
            const counterpartCompany =
              PAGE_ROLE === 'SELLER'
                ? sub.buyer_company
                : sub.seller_company;

            const isMyRequest =
              sub.created_by === null || sub.created_by === currentUserId;
            const showAcceptReject =
              sub.status === 'PENDING' && !isMyRequest;
            const showGenerate = sub.status === 'ACTIVE';
            const showPauseResume =
              sub.status === 'ACTIVE' || sub.status === 'PAUSED';
            const showDelete =
              sub.status !== 'ENDED' &&
              sub.status !== 'CANCELLED' &&
              sub.status !== 'REJECTED';

            return (
              <div
                key={sub.id}
                className="overflow-hidden rounded-xl bg-white shadow-sm"
              >
                {/* 요약 행 */}
                <button
                  type="button"
                  onClick={() => handleToggleRow(sub.id)}
                  className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-gray-50"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="truncate font-medium text-gray-900">
                        {firstName}
                        {extra}
                      </span>
                      <span
                        className={cn(
                          'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium',
                          cfg.className
                        )}
                      >
                        {cfg.label}
                      </span>
                    </div>
                    <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-gray-500">
                      <span>
                        {COUNTERPART_LABEL}: {counterpartName ?? '-'}
                        {counterpartCompany ? ` (${counterpartCompany})` : ''}
                      </span>
                      <span>주기: {formatScheduleLabel(sub)}</span>
                      <span>
                        다음 배송일: {formatDate(sub.next_delivery_date)}
                      </span>
                      <span>
                        회당 {sub.total_amount.toLocaleString('ko-KR')}원
                      </span>
                    </div>
                  </div>
                  <div className="flex-shrink-0 text-gray-400">
                    {isExpanded ? (
                      <ChevronUp className="h-4 w-4" />
                    ) : (
                      <ChevronDown className="h-4 w-4" />
                    )}
                  </div>
                </button>

                {/* 펼침 영역 */}
                {isExpanded && (
                  <div className="border-t border-gray-100 bg-gray-50/50 p-4">
                    <div className="grid gap-4 sm:grid-cols-2">
                      <div>
                        <p className="text-xs text-gray-500">기간</p>
                        <p className="text-sm text-gray-900">
                          {formatDate(sub.start_date)} ~{' '}
                          {sub.end_date ? formatDate(sub.end_date) : '무기한'}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-gray-500">총 주기</p>
                        <p className="text-sm text-gray-900">
                          {formatScheduleLabel(sub)}
                        </p>
                      </div>
                      {sub.delivery_address && (
                        <div className="sm:col-span-2">
                          <p className="text-xs text-gray-500">배송지</p>
                          <p className="whitespace-pre-wrap text-sm text-gray-900">
                            {sub.delivery_address}
                          </p>
                        </div>
                      )}
                      {sub.notes && (
                        <div className="sm:col-span-2">
                          <p className="text-xs text-gray-500">메모</p>
                          <p className="whitespace-pre-wrap text-sm text-gray-900">
                            {sub.notes}
                          </p>
                        </div>
                      )}
                    </div>

                    {/* 상품 항목 리스트 */}
                    {sub.items.length > 0 && (
                      <div className="mt-4">
                        <p className="mb-2 text-xs text-gray-500">정기배송 상품</p>
                        <div className="space-y-2">
                          {sub.items.map((item) => (
                            <div
                              key={item.id}
                              className="rounded-lg bg-white p-3 text-sm shadow-sm"
                            >
                              <p className="mb-1 font-medium text-gray-900">
                                {item.product_name ?? '상품 정보 없음'}
                              </p>
                              <div className="flex justify-between text-gray-700">
                                <span>
                                  수량 {item.quantity}
                                  {item.unit ?? ''} ×{' '}
                                  {item.unit_price.toLocaleString('ko-KR')}원
                                </span>
                                <span className="font-medium text-gray-900">
                                  {(
                                    item.quantity * item.unit_price
                                  ).toLocaleString('ko-KR')}
                                  원
                                </span>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* 액션 버튼 */}
                    <div className="mt-4 flex flex-wrap gap-2">
                      {showAcceptReject && (
                        <>
                          <button
                            onClick={() => acceptSubscription.mutate(sub.id)}
                            disabled={
                              acceptSubscription.isPending ||
                              rejectSubscription.isPending
                            }
                            className="rounded-lg bg-blue-600 px-3 py-2 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                          >
                            수락
                          </button>
                          <button
                            onClick={() => rejectSubscription.mutate(sub.id)}
                            disabled={
                              acceptSubscription.isPending ||
                              rejectSubscription.isPending
                            }
                            className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                          >
                            거절
                          </button>
                        </>
                      )}
                      {showGenerate && (
                        <button
                          onClick={() => handleGenerateOrder(sub)}
                          disabled={generateOrder.isPending}
                          className="inline-flex items-center gap-1 rounded-lg bg-primary-600 px-3 py-2 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50"
                        >
                          <PackageCheck className="h-3.5 w-3.5" />
                          이번 회차 주문 생성
                        </button>
                      )}
                      {showPauseResume && (
                        <button
                          onClick={() => handleTogglePause(sub)}
                          disabled={updateGeneric.isPending}
                          className="inline-flex items-center gap-1 rounded-lg border border-gray-300 bg-white px-3 py-2 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                        >
                          {sub.status === 'ACTIVE' ? (
                            <>
                              <Pause className="h-3.5 w-3.5" />
                              일시정지
                            </>
                          ) : (
                            <>
                              <Play className="h-3.5 w-3.5" />
                              재개
                            </>
                          )}
                        </button>
                      )}
                      <button
                        onClick={() => handleJumpToPartner(sub)}
                        className="inline-flex items-center gap-1 rounded-lg border border-gray-300 bg-white px-3 py-2 text-xs font-medium text-gray-700 hover:bg-gray-50"
                      >
                        <ExternalLink className="h-3.5 w-3.5" />
                        거래처로 이동
                      </button>
                      {showDelete && (
                        <button
                          onClick={() => handleDelete(sub)}
                          disabled={deleteSubscription.isPending}
                          className="inline-flex items-center gap-1 rounded-lg border border-red-300 bg-white px-3 py-2 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                          해지
                        </button>
                      )}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* 거래처 모달 — 행에서 "거래처로 이동" 클릭 시 */}
      <PartnerDetailModal
        partner={selectedPartner}
        myRole={PAGE_ROLE}
        onClose={() => setSelectedPartner(null)}
      />
    </div>
  );
}
