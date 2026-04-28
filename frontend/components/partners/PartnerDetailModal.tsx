'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  Star,
  Building2,
  Phone,
  MessageCircle,
  FileText,
  Plus,
  Edit2,
  Pause,
  Play,
  Trash2,
  PackageCheck,
  Inbox,
  Clock,
} from 'lucide-react';
import Modal from '@/components/common/Modal';
import StatusBadge from '@/components/common/StatusBadge';
import SubscriptionFormModal from '@/components/subscriptions/SubscriptionFormModal';
import {
  usePartnerStats,
  useTogglePartnerFavorite,
  useUpdatePartner,
} from '@/hooks/usePartners';
import {
  useAcceptSubscription,
  useDeleteSubscription,
  useGenerateSubscriptionOrder,
  useRejectSubscription,
  useSubscriptions,
  useUpdateSubscription,
} from '@/hooks/useSubscriptions';
import { useCreateChatRoom } from '@/hooks/useChat';
import { useAuthStore } from '@/store/authStore';
import { SUBSCRIPTION_STATUS_CONFIG } from '@/constants/status';
import type {
  Partner,
  Subscription,
  SubscriptionFrequency,
  SubscriptionStatus,
} from '@/types';

interface PartnerDetailModalProps {
  partner: Partner | null;
  myRole: 'SELLER' | 'BUYER';
  onClose: () => void;
  /**
   * V1.5 Phase 3: 거래처 삭제 핸들러 (활성 정기배송 PAUSED → soft-delete 일괄 처리).
   * 페이지 컨테이너에서 정기배송/거래처 React Query 무효화까지 책임지므로
   * 모달은 클릭 위임만 수행한다. 부재 시 삭제 버튼은 노출되지 않는다.
   */
  onDelete?: (partner: Partner) => void;
  deletePending?: boolean;
}

const FREQUENCY_LABEL: Record<SubscriptionFrequency, string> = {
  WEEKLY: '매주',
  BIWEEKLY: '격주',
  MONTHLY: '매월',
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

export default function PartnerDetailModal({
  partner,
  myRole,
  onClose,
  onDelete,
  deletePending,
}: PartnerDetailModalProps) {
  const router = useRouter();
  const isOpen = !!partner;
  const { user } = useAuthStore();
  const currentUserId = user?.id ?? '';

  // 인라인 편집
  const [editingNickname, setEditingNickname] = useState(false);
  const [editingNotes, setEditingNotes] = useState(false);
  const [nicknameDraft, setNicknameDraft] = useState('');
  const [notesDraft, setNotesDraft] = useState('');

  // 정기배송
  const [expandedSubId, setExpandedSubId] = useState<string | null>(null);
  const [showSubForm, setShowSubForm] = useState(false);
  const [chatPending, setChatPending] = useState(false);

  // partner 변경 시 편집 상태 초기화
  useEffect(() => {
    setEditingNickname(false);
    setEditingNotes(false);
    setNicknameDraft(partner?.nickname ?? '');
    setNotesDraft(partner?.notes ?? '');
    setExpandedSubId(null);
  }, [partner?.id, partner?.nickname, partner?.notes]);

  const toggleFavorite = useTogglePartnerFavorite();
  const updatePartner = useUpdatePartner();

  const statsQuery = usePartnerStats(partner?.id ?? '');
  const stats = statsQuery.data?.data;

  // 이 거래처와의 정기배송만 조회 (partner_user_id 로 필터)
  const subsQuery = useSubscriptions(
    partner ? { partner_user_id: partner.partner_user_id, limit: 200 } : undefined
  );
  const subscriptions: Subscription[] = subsQuery.data?.data ?? [];

  // 정기배송 액션 mutation들
  const generateOrder = useGenerateSubscriptionOrder();
  const deleteSubscription = useDeleteSubscription();
  const acceptSubscription = useAcceptSubscription();
  const rejectSubscription = useRejectSubscription();
  const createChatRoom = useCreateChatRoom();

  // V1.6 — PENDING 정기배송 분리.
  // 받은 요청: status='PENDING' 이고 created_by != currentUser
  // 보낸 요청: status='PENDING' 이고 created_by == currentUser
  // 메인 리스트: 그 외 모든 상태 (ACTIVE/PAUSED/ENDED/CANCELLED/REJECTED)
  const incomingPendingSubs = useMemo(
    () =>
      subscriptions.filter(
        (s) =>
          s.status === 'PENDING' &&
          s.created_by !== null &&
          s.created_by !== currentUserId
      ),
    [subscriptions, currentUserId]
  );
  const outgoingPendingSubs = useMemo(
    () =>
      subscriptions.filter(
        (s) =>
          s.status === 'PENDING' &&
          (s.created_by === null || s.created_by === currentUserId)
      ),
    [subscriptions, currentUserId]
  );
  const mainListSubs = useMemo(
    () => subscriptions.filter((s) => s.status !== 'PENDING'),
    [subscriptions]
  );

  // 즐겨찾기 우선 + 최근 등록 순으로 정렬된 메인 정기배송
  const sortedSubs = useMemo(
    () =>
      [...mainListSubs].sort((a, b) => {
        // ACTIVE > PAUSED > ENDED/CANCELLED/REJECTED
        const order: Record<string, number> = {
          ACTIVE: 0,
          PAUSED: 1,
          ENDED: 2,
          CANCELLED: 3,
          REJECTED: 4,
        };
        const ao = order[a.status] ?? 9;
        const bo = order[b.status] ?? 9;
        if (ao !== bo) return ao - bo;
        return (
          new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
        );
      }),
    [mainListSubs]
  );

  if (!partner) {
    return <Modal isOpen={false} onClose={onClose} title="" size="xl">{null}</Modal>;
  }

  // V1.6 — 본인이 보낸 거래처 요청은 아직 거래처가 아님.
  // 채팅/주문/즐겨찾기/정기배송 등 모든 거래 액션을 잠그고, 요청 회수만 허용한다.
  const isPendingOutgoing = partner.status === 'PENDING_OUTGOING';

  const handleToggleFavorite = () => {
    if (isPendingOutgoing) return;
    toggleFavorite.mutate({ id: partner.id, is_favorite: !partner.is_favorite });
  };

  const saveNickname = () => {
    const value = nicknameDraft.trim();
    if (value === (partner.nickname ?? '')) {
      setEditingNickname(false);
      return;
    }
    updatePartner.mutate(
      { id: partner.id, data: { nickname: value || null } },
      {
        onSettled: () => setEditingNickname(false),
      }
    );
  };

  const saveNotes = () => {
    const value = notesDraft.trim();
    if (value === (partner.notes ?? '')) {
      setEditingNotes(false);
      return;
    }
    updatePartner.mutate(
      { id: partner.id, data: { notes: value || null } },
      {
        onSettled: () => setEditingNotes(false),
      }
    );
  };

  const handleStartChat = async () => {
    if (chatPending) return;
    setChatPending(true);
    try {
      const res = await createChatRoom.mutateAsync({
        partner_user_id: partner.partner_user_id,
      });
      const path =
        myRole === 'SELLER'
          ? `/seller/chat?room_id=${res.data.id}`
          : `/buyer/chat?room_id=${res.data.id}`;
      router.push(path);
      onClose();
    } catch (e) {
      console.error('[PartnerDetailModal] 채팅방 생성 실패:', e);
    } finally {
      setChatPending(false);
    }
  };

  const handleCreateOrder = () => {
    // BUYER: browse 로 sellerFilter prefill / SELLER: V1.5 에선 상품 작성 페이지 미존재
    if (myRole === 'BUYER') {
      router.push(`/buyer/browse?seller_id=${partner.partner_user_id}`);
      onClose();
    }
  };

  const handleGenerateOrder = (subId: string) => {
    if (
      !confirm(
        '이번 회차 주문을 즉시 생성하시겠습니까?\n주문/캘린더에 반영되며, 다음 회차 일정이 자동 진행됩니다.'
      )
    )
      return;
    generateOrder.mutate(subId);
  };

  const handleDeleteSubscription = (subId: string) => {
    if (!confirm('이 정기배송을 삭제하시겠습니까? (복구 불가)')) return;
    deleteSubscription.mutate(subId);
  };

  return (
    <>
      <Modal
        isOpen={isOpen}
        onClose={onClose}
        title={
          partner.nickname ||
          partner.partner_company ||
          partner.partner_name ||
          '거래처 상세'
        }
        size="xl"
        footer={
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm hover:bg-gray-50"
          >
            닫기
          </button>
        }
      >
        <div className="space-y-6">
          {/* 헤더 — 즐겨찾기 + 상태 + 빠른 액션 */}
          <div className="flex items-center justify-between rounded-lg border border-gray-200 bg-gray-50 p-3">
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={handleToggleFavorite}
                disabled={isPendingOutgoing}
                title={isPendingOutgoing ? '승인 후 사용 가능합니다' : undefined}
                className={`text-gray-300 ${
                  isPendingOutgoing
                    ? 'cursor-not-allowed opacity-40'
                    : 'hover:text-yellow-400'
                }`}
                aria-label={partner.is_favorite ? '즐겨찾기 해제' : '즐겨찾기 등록'}
              >
                <Star
                  className={`h-5 w-5 ${
                    partner.is_favorite ? 'fill-yellow-400 text-yellow-400' : ''
                  }`}
                />
              </button>
              <StatusBadge status={partner.status} />
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleStartChat}
                disabled={chatPending || isPendingOutgoing}
                title={
                  isPendingOutgoing
                    ? '승인 후 사용 가능합니다'
                    : undefined
                }
                className={`inline-flex items-center gap-1 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 ${
                  isPendingOutgoing
                    ? 'cursor-not-allowed opacity-40'
                    : 'hover:bg-gray-50 disabled:opacity-50'
                }`}
              >
                <MessageCircle className="h-3.5 w-3.5" />
                채팅 시작
              </button>
              {myRole === 'BUYER' && (
                <button
                  type="button"
                  onClick={handleCreateOrder}
                  disabled={isPendingOutgoing}
                  title={
                    isPendingOutgoing
                      ? '승인 후 사용 가능합니다'
                      : undefined
                  }
                  className={`inline-flex items-center gap-1 rounded-lg bg-primary-600 px-3 py-1.5 text-xs font-medium text-white ${
                    isPendingOutgoing
                      ? 'cursor-not-allowed opacity-40'
                      : 'hover:bg-primary-700'
                  }`}
                >
                  <FileText className="h-3.5 w-3.5" />
                  주문 작성
                </button>
              )}
              {/* V1.5 Phase 3: 거래처 삭제 (페이지 컨테이너 핸들러로 위임) */}
              {/* V1.6: PENDING_OUTGOING 이면 "요청 회수" 라벨로 표시 */}
              {onDelete && (
                <button
                  type="button"
                  onClick={() => onDelete(partner)}
                  disabled={deletePending}
                  className="inline-flex items-center gap-1 rounded-lg border border-red-300 bg-white px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  {isPendingOutgoing ? '요청 회수' : '거래처 삭제'}
                </button>
              )}
            </div>
          </div>

          {/* V1.6 — 보낸 거래처 요청 안내 */}
          {isPendingOutgoing && (
            <div className="flex items-center gap-2 rounded-lg border border-yellow-200 bg-yellow-50 p-3 text-sm text-yellow-800">
              <Clock className="h-4 w-4 flex-shrink-0" />
              <span>
                보낸 거래처 요청이 수락되기 전까지 채팅 시작·주문 작성·정기배송
                등록 등의 거래 액션을 사용할 수 없습니다.
              </span>
            </div>
          )}

          {/* 섹션 1 — 프로필 */}
          <section>
            <h3 className="mb-2 text-sm font-semibold text-gray-700">프로필</h3>
            <div className="grid grid-cols-2 gap-3 rounded-lg border border-gray-200 p-4">
              <div>
                <p className="text-xs text-gray-500">이름</p>
                <p className="text-sm font-medium text-gray-900">
                  {partner.partner_name ?? '-'}
                </p>
              </div>
              <div>
                <p className="text-xs text-gray-500">회사명</p>
                <p className="flex items-center gap-1 text-sm font-medium text-gray-900">
                  {partner.partner_company ? (
                    <>
                      <Building2 className="h-3.5 w-3.5 text-gray-400" />
                      {partner.partner_company}
                    </>
                  ) : (
                    '-'
                  )}
                </p>
              </div>
              <div>
                <p className="text-xs text-gray-500">역할</p>
                <p className="text-sm text-gray-900">
                  {partner.partner_role === 'BUYER' ? '구매자' : '판매자'}
                </p>
              </div>
              <div>
                <p className="text-xs text-gray-500">연락처</p>
                <p className="flex items-center gap-1 text-sm text-gray-900">
                  {partner.partner_phone ? (
                    <>
                      <Phone className="h-3.5 w-3.5 text-gray-400" />
                      {partner.partner_phone}
                    </>
                  ) : (
                    '-'
                  )}
                </p>
              </div>
            </div>
          </section>

          {/* 섹션 2 — 별칭/메모 인라인 편집 */}
          <section>
            <h3 className="mb-2 text-sm font-semibold text-gray-700">메모</h3>
            <div className="space-y-2 rounded-lg border border-gray-200 p-4">
              {/* 별칭 */}
              <div>
                <p className="mb-1 text-xs text-gray-500">별칭 (내부 표시명)</p>
                {editingNickname ? (
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={nicknameDraft}
                      onChange={(e) => setNicknameDraft(e.target.value)}
                      onBlur={saveNickname}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          saveNickname();
                        } else if (e.key === 'Escape') {
                          setNicknameDraft(partner.nickname ?? '');
                          setEditingNickname(false);
                        }
                      }}
                      autoFocus
                      placeholder="별칭을 입력하세요"
                      className="flex-1 rounded-lg border border-primary-500 px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-primary-500"
                    />
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => {
                      setNicknameDraft(partner.nickname ?? '');
                      setEditingNickname(true);
                    }}
                    className="group flex w-full items-center gap-2 rounded-lg px-2 py-1 text-left text-sm text-gray-900 hover:bg-gray-50"
                  >
                    <span>
                      {partner.nickname || (
                        <span className="text-gray-400">별칭을 입력하세요</span>
                      )}
                    </span>
                    <Edit2 className="h-3 w-3 text-gray-400 opacity-0 group-hover:opacity-100" />
                  </button>
                )}
              </div>

              {/* 메모 */}
              <div>
                <p className="mb-1 text-xs text-gray-500">메모</p>
                {editingNotes ? (
                  <div className="flex flex-col gap-2">
                    <textarea
                      value={notesDraft}
                      onChange={(e) => setNotesDraft(e.target.value)}
                      onBlur={saveNotes}
                      onKeyDown={(e) => {
                        if (e.key === 'Escape') {
                          setNotesDraft(partner.notes ?? '');
                          setEditingNotes(false);
                        }
                      }}
                      autoFocus
                      rows={3}
                      placeholder="이 거래처에 대한 메모를 남기세요"
                      className="w-full rounded-lg border border-primary-500 px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-primary-500"
                    />
                    <button
                      type="button"
                      onClick={saveNotes}
                      className="self-end rounded-lg bg-primary-600 px-3 py-1 text-xs text-white hover:bg-primary-700"
                    >
                      저장
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => {
                      setNotesDraft(partner.notes ?? '');
                      setEditingNotes(true);
                    }}
                    className="group flex w-full items-start gap-2 rounded-lg px-2 py-1 text-left text-sm text-gray-900 hover:bg-gray-50"
                  >
                    <span className="flex-1 whitespace-pre-wrap">
                      {partner.notes || (
                        <span className="text-gray-400">
                          이 거래처에 대한 메모를 남기세요
                        </span>
                      )}
                    </span>
                    <Edit2 className="mt-1 h-3 w-3 flex-shrink-0 text-gray-400 opacity-0 group-hover:opacity-100" />
                  </button>
                )}
              </div>
            </div>
          </section>

          {/* 섹션 3 — 거래 통계 */}
          <section>
            <h3 className="mb-2 text-sm font-semibold text-gray-700">거래 통계</h3>
            <div className="grid grid-cols-4 gap-2">
              <div className="rounded-lg border border-gray-200 bg-white p-3">
                <p className="text-xs text-gray-500">총 주문</p>
                <p className="mt-1 text-lg font-semibold text-gray-900">
                  {statsQuery.isLoading ? '-' : (stats?.total_orders ?? 0)}건
                </p>
              </div>
              <div className="rounded-lg border border-gray-200 bg-white p-3">
                <p className="text-xs text-gray-500">총 거래액</p>
                <p className="mt-1 text-lg font-semibold text-gray-900">
                  {statsQuery.isLoading
                    ? '-'
                    : (stats?.total_amount ?? 0).toLocaleString('ko-KR')}
                  원
                </p>
              </div>
              <div className="rounded-lg border border-gray-200 bg-white p-3">
                <p className="text-xs text-gray-500">최근 주문일</p>
                <p className="mt-1 text-sm font-medium text-gray-900">
                  {statsQuery.isLoading
                    ? '-'
                    : stats?.last_order_date
                    ? formatDate(stats.last_order_date)
                    : '없음'}
                </p>
              </div>
              <div className="rounded-lg border border-gray-200 bg-white p-3">
                <p className="text-xs text-gray-500">활성 정기배송</p>
                <p className="mt-1 text-lg font-semibold text-gray-900">
                  {statsQuery.isLoading
                    ? '-'
                    : (stats?.active_subscriptions ?? 0)}
                  건
                </p>
              </div>
            </div>
          </section>

          {/* V1.6 — 받은 정기배송 요청 (보낸 거래처 요청 상태에선 정기배송 자체를 노출하지 않음) */}
          {!isPendingOutgoing && incomingPendingSubs.length > 0 && (
            <section className="rounded-lg border border-blue-200 bg-blue-50 p-3">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-blue-900">
                <Inbox className="h-4 w-4" />
                받은 정기배송 요청 ({incomingPendingSubs.length})
              </h3>
              <ul className="mt-2 space-y-2">
                {incomingPendingSubs.map((sub) => {
                  const firstItem = sub.items?.[0];
                  const itemSummary = firstItem?.product_name ?? '상품 정보 없음';
                  const extraCount =
                    sub.items.length > 1 ? ` 외 ${sub.items.length - 1}건` : '';
                  return (
                    <li
                      key={sub.id}
                      className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-white p-3"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-gray-900">
                          {itemSummary}{extraCount}
                        </p>
                        <p className="mt-0.5 text-xs text-gray-500">
                          {FREQUENCY_LABEL[sub.frequency]} · 시작 {formatDate(sub.start_date)}
                          {' · '}
                          {sub.total_amount.toLocaleString('ko-KR')}원/회
                        </p>
                      </div>
                      <div className="flex flex-shrink-0 gap-2">
                        <button
                          type="button"
                          onClick={() => acceptSubscription.mutate(sub.id)}
                          disabled={
                            acceptSubscription.isPending ||
                            rejectSubscription.isPending
                          }
                          className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                        >
                          수락
                        </button>
                        <button
                          type="button"
                          onClick={() => rejectSubscription.mutate(sub.id)}
                          disabled={
                            acceptSubscription.isPending ||
                            rejectSubscription.isPending
                          }
                          className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                        >
                          거절
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </section>
          )}

          {/* V1.6 — 보낸 정기배송 요청 (수락 대기 중) */}
          {!isPendingOutgoing && outgoingPendingSubs.length > 0 && (
            <section className="rounded-lg border border-yellow-200 bg-yellow-50 p-3">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-yellow-900">
                <Clock className="h-4 w-4" />
                보낸 정기배송 요청 ({outgoingPendingSubs.length})
              </h3>
              <ul className="mt-2 space-y-2">
                {outgoingPendingSubs.map((sub) => {
                  const firstItem = sub.items?.[0];
                  const itemSummary = firstItem?.product_name ?? '상품 정보 없음';
                  const extraCount =
                    sub.items.length > 1 ? ` 외 ${sub.items.length - 1}건` : '';
                  return (
                    <li
                      key={sub.id}
                      className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-white p-3"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-gray-900">
                          {itemSummary}{extraCount}
                        </p>
                        <p className="mt-0.5 text-xs text-gray-500">
                          {FREQUENCY_LABEL[sub.frequency]} · 시작 {formatDate(sub.start_date)}
                          {' · '}
                          {sub.total_amount.toLocaleString('ko-KR')}원/회
                        </p>
                      </div>
                      <div className="flex flex-shrink-0 items-center gap-2">
                        <span className="text-xs text-yellow-700">
                          수락 대기 중
                        </span>
                        <button
                          type="button"
                          onClick={() => {
                            if (
                              window.confirm(
                                '이 정기배송 요청을 회수하시겠습니까?'
                              )
                            ) {
                              rejectSubscription.mutate(sub.id);
                            }
                          }}
                          disabled={rejectSubscription.isPending}
                          className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                        >
                          요청 회수
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </section>
          )}

          {/* 섹션 4 — 정기배송 (메인 리스트, ACTIVE/PAUSED/ENDED 등) */}
          {/* V1.6: PENDING_OUTGOING(승인 대기) 상태에선 정기배송 섹션 자체를 숨김 */}
          {!isPendingOutgoing && (
          <section>
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-gray-700">
                정기배송 ({sortedSubs.length})
              </h3>
              <button
                type="button"
                onClick={() => setShowSubForm(true)}
                className="inline-flex items-center gap-1 rounded-lg bg-primary-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-700"
              >
                <Plus className="h-3.5 w-3.5" />새 정기배송
              </button>
            </div>

            {subsQuery.isLoading ? (
              <p className="rounded-lg border border-gray-200 p-4 text-center text-sm text-gray-400">
                로딩 중...
              </p>
            ) : sortedSubs.length === 0 ? (
              <p className="rounded-lg border border-dashed border-gray-300 p-4 text-center text-sm text-gray-400">
                등록된 정기배송이 없습니다. 우측 상단 버튼으로 새 정기배송을
                등록하세요.
              </p>
            ) : (
              <ul className="space-y-2">
                {sortedSubs.map((sub) => {
                  const expanded = expandedSubId === sub.id;
                  const firstItem = sub.items?.[0];
                  const itemSummary =
                    firstItem?.product_name ?? '상품 정보 없음';
                  const extraCount =
                    sub.items.length > 1 ? ` 외 ${sub.items.length - 1}건` : '';
                  const cfg =
                    SUBSCRIPTION_STATUS_CONFIG[
                      sub.status as SubscriptionStatus
                    ] ?? {
                      label: sub.status,
                      className: 'bg-gray-100 text-gray-600',
                    };
                  const targetStatus =
                    sub.status === 'ACTIVE' ? 'PAUSED' : 'ACTIVE';

                  return (
                    <li
                      key={sub.id}
                      className="rounded-lg border border-gray-200 bg-white"
                    >
                      <button
                        type="button"
                        onClick={() =>
                          setExpandedSubId(expanded ? null : sub.id)
                        }
                        className="flex w-full items-start justify-between gap-3 p-3 text-left hover:bg-gray-50"
                      >
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-medium text-gray-900">
                            {itemSummary}
                            {extraCount}
                          </p>
                          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-gray-500">
                            <span>{FREQUENCY_LABEL[sub.frequency]}</span>
                            <span>·</span>
                            <span>다음 배송 {formatDate(sub.next_delivery_date)}</span>
                            <span>·</span>
                            <span>
                              {sub.total_amount.toLocaleString('ko-KR')}원/회
                            </span>
                          </div>
                        </div>
                        <span
                          className={`flex-shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${cfg.className}`}
                        >
                          {cfg.label}
                        </span>
                      </button>

                      {expanded && (
                        <div className="space-y-3 border-t border-gray-100 bg-gray-50 p-3">
                          {/* 상세 정보 */}
                          <div className="grid grid-cols-2 gap-2 text-xs">
                            <div>
                              <p className="text-gray-500">시작일</p>
                              <p className="text-gray-900">
                                {formatDate(sub.start_date)}
                              </p>
                            </div>
                            <div>
                              <p className="text-gray-500">종료일</p>
                              <p className="text-gray-900">
                                {sub.end_date ? formatDate(sub.end_date) : '무기한'}
                              </p>
                            </div>
                            {sub.delivery_address && (
                              <div className="col-span-2">
                                <p className="text-gray-500">배송지</p>
                                <p className="whitespace-pre-wrap text-gray-900">
                                  {sub.delivery_address}
                                </p>
                              </div>
                            )}
                            {sub.notes && (
                              <div className="col-span-2">
                                <p className="text-gray-500">메모</p>
                                <p className="whitespace-pre-wrap text-gray-900">
                                  {sub.notes}
                                </p>
                              </div>
                            )}
                          </div>

                          {/* 항목 리스트 */}
                          <div>
                            <p className="mb-1 text-xs font-medium text-gray-600">
                              상품 항목
                            </p>
                            <ul className="space-y-1">
                              {sub.items.map((it) => (
                                <li
                                  key={it.id}
                                  className="flex items-center justify-between rounded-md bg-white px-2 py-1.5 text-xs"
                                >
                                  <span className="truncate text-gray-900">
                                    {it.product_name ?? '상품 정보 없음'}
                                  </span>
                                  <span className="flex-shrink-0 text-gray-600">
                                    {it.quantity}
                                    {it.unit} ×{' '}
                                    {it.unit_price.toLocaleString('ko-KR')}원
                                  </span>
                                </li>
                              ))}
                            </ul>
                          </div>

                          {/* 액션 버튼 */}
                          <div className="flex flex-wrap gap-2">
                            {sub.status === 'ACTIVE' && (
                              <SubActionButton
                                icon={<PackageCheck className="h-3.5 w-3.5" />}
                                onClick={() => handleGenerateOrder(sub.id)}
                                disabled={generateOrder.isPending}
                                label="이번 회차 주문 생성"
                                variant="primary"
                              />
                            )}
                            {(sub.status === 'ACTIVE' ||
                              sub.status === 'PAUSED') && (
                              <ToggleStatusButton
                                subId={sub.id}
                                targetStatus={targetStatus}
                              />
                            )}
                            <SubActionButton
                              icon={<Trash2 className="h-3.5 w-3.5" />}
                              onClick={() => handleDeleteSubscription(sub.id)}
                              disabled={deleteSubscription.isPending}
                              label="삭제"
                              variant="danger"
                            />
                          </div>
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
          )}
        </div>
      </Modal>

      {/* 새 정기배송 등록 폼 모달 */}
      {partner && (
        <SubscriptionFormModal
          isOpen={showSubForm}
          onClose={() => setShowSubForm(false)}
          partner={partner}
          myRole={myRole}
        />
      )}
    </>
  );
}

// ===========================================
// 서브 컴포넌트
// ===========================================

interface SubActionButtonProps {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  variant: 'primary' | 'secondary' | 'danger';
}

function SubActionButton({
  icon,
  label,
  onClick,
  disabled,
  variant,
}: SubActionButtonProps) {
  const cls =
    variant === 'primary'
      ? 'bg-primary-600 text-white hover:bg-primary-700'
      : variant === 'danger'
      ? 'border border-red-300 bg-white text-red-600 hover:bg-red-50'
      : 'border border-gray-300 bg-white text-gray-700 hover:bg-gray-50';
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs font-medium disabled:opacity-50 ${cls}`}
    >
      {icon}
      {label}
    </button>
  );
}

interface ToggleStatusButtonProps {
  subId: string;
  targetStatus: 'ACTIVE' | 'PAUSED';
}

function ToggleStatusButton({ subId, targetStatus }: ToggleStatusButtonProps) {
  const updateSub = useUpdateSubscription(subId);
  const isPause = targetStatus === 'PAUSED';
  return (
    <button
      type="button"
      onClick={() => updateSub.mutate({ status: targetStatus })}
      disabled={updateSub.isPending}
      className="inline-flex items-center gap-1 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
    >
      {isPause ? (
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
  );
}
