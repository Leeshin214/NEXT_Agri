'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Star, Plus, MessageCircle, FileText, Trash2, Inbox, Clock } from 'lucide-react';
import PageHeader from '@/components/common/PageHeader';
import DataTable, { type Column } from '@/components/common/DataTable';
import SearchFilterBar from '@/components/common/SearchFilterBar';
import StatusBadge from '@/components/common/StatusBadge';
import AddPartnerModal from '@/components/partners/AddPartnerModal';
import PartnerDetailModal from '@/components/partners/PartnerDetailModal';
import {
  useAcceptPartner,
  useDeletePartner,
  usePartners,
  useRejectPartner,
  useTogglePartnerFavorite,
} from '@/hooks/usePartners';
import {
  useSubscriptions,
  useUpdateSubscriptionGeneric,
} from '@/hooks/useSubscriptions';
import { useCreateChatRoom } from '@/hooks/useChat';
import { PARTNER_STATUS_OPTIONS } from '@/constants/options';
import type { Partner } from '@/types';

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('ko-KR', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  });
}

export default function SellerPartnersPage() {
  const router = useRouter();
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [favoriteOnly, setFavoriteOnly] = useState(false);
  const [showAddModal, setShowAddModal] = useState(false);
  const [chatPendingId, setChatPendingId] = useState<string | null>(null);
  const [selectedPartner, setSelectedPartner] = useState<Partner | null>(null);
  const [deletePendingId, setDeletePendingId] = useState<string | null>(null);

  // 서버 사이드 필터 (search, partner_status)
  // V1.5 Phase 3: is_favorite 필터는 백엔드 list_partners 가 미지원 → 클라이언트 필터링
  const { data, isLoading } = usePartners({
    partner_status: statusFilter || undefined,
    search: search || undefined,
  });
  const partners = data?.data ?? [];

  // V1.6 — 양방향 승인: 받은 요청 / 보낸 요청 / 활성으로 분리
  const incomingRequests = useMemo(
    () => partners.filter((p) => p.status === 'PENDING_INCOMING'),
    [partners]
  );
  const outgoingRequests = useMemo(
    () => partners.filter((p) => p.status === 'PENDING_OUTGOING'),
    [partners]
  );
  // 메인 리스트는 ACTIVE/INACTIVE/PENDING(deprecated) 만 노출
  const mainListPartners = useMemo(
    () =>
      partners.filter(
        (p) =>
          p.status !== 'PENDING_OUTGOING' && p.status !== 'PENDING_INCOMING'
      ),
    [partners]
  );

  // 즐겨찾기 우선 정렬: is_favorite desc → created_at desc (즐겨찾기만 모드에서도 동일)
  const sortedPartners = useMemo(
    () =>
      [...mainListPartners].sort((a, b) => {
        if (a.is_favorite !== b.is_favorite) {
          return a.is_favorite ? -1 : 1;
        }
        return (
          new Date(b.created_at).getTime() -
          new Date(a.created_at).getTime()
        );
      }),
    [mainListPartners]
  );

  // V1.5 Phase 3: 즐겨찾기 토글이 켜져 있으면 is_favorite 만 노출
  const visiblePartners = useMemo(
    () =>
      favoriteOnly
        ? sortedPartners.filter((p) => p.is_favorite)
        : sortedPartners,
    [sortedPartners, favoriteOnly]
  );

  const toggleFavorite = useTogglePartnerFavorite();
  const deletePartner = useDeletePartner();
  const acceptPartner = useAcceptPartner();
  const rejectPartner = useRejectPartner();
  const updateSubscription = useUpdateSubscriptionGeneric();
  const createChatRoom = useCreateChatRoom();

  // 거래처 삭제 시 일시정지 처리를 위해 활성 정기배송 목록 조회
  // (특정 partner_user_id 로 좁히지 않고 전체를 받아온 뒤 partner_id 로 매칭)
  const subData = useSubscriptions({ status: 'ACTIVE', limit: 200 });

  // 모달 열려 있을 때 partners 가 갱신되면(별칭/즐겨찾기 등 PATCH 결과 반영)
  // selectedPartner 도 최신 row 로 동기화
  useEffect(() => {
    if (!selectedPartner) return;
    const fresh = partners.find((p) => p.id === selectedPartner.id);
    if (fresh && fresh !== selectedPartner) {
      setSelectedPartner(fresh);
    }
    // partners 가 빠졌으면 모달 닫기 (삭제 등)
    if (!fresh) {
      setSelectedPartner(null);
    }
  }, [partners, selectedPartner]);

  const handleToggleFavorite = (partner: Partner) => {
    toggleFavorite.mutate({
      id: partner.id,
      is_favorite: !partner.is_favorite,
    });
  };

  const handleStartChat = async (partner: Partner) => {
    if (chatPendingId) return;
    setChatPendingId(partner.id);
    try {
      const res = await createChatRoom.mutateAsync({
        partner_user_id: partner.partner_user_id,
      });
      router.push(`/seller/chat?room_id=${res.data.id}`);
    } catch (e) {
      console.error('[seller/partners] 채팅방 생성 실패:', e);
    } finally {
      setChatPendingId(null);
    }
  };

  /**
   * V1.5 Phase 3: 거래처 soft-delete.
   * - 활성 정기배송이 있으면 먼저 PAUSED 로 전환 (데이터 보존을 위해 삭제하지 않음)
   * - 그 후 거래처 자체를 soft-delete
   * - 모달이 열려 있으면 닫음
   */
  const handleDeletePartner = async (partner: Partner) => {
    if (deletePendingId) return;
    const confirmed = window.confirm(
      `'${partner.nickname || partner.partner_company || partner.partner_name || ''}' 거래처를 삭제하시겠습니까?\n진행 중인 정기배송이 일시정지됩니다.`
    );
    if (!confirmed) return;

    setDeletePendingId(partner.id);
    try {
      // 1) 활성 정기배송 일시정지
      const activeSubs = (subData.data?.data ?? []).filter(
        (s) => s.partner_id === partner.id && s.status === 'ACTIVE'
      );
      await Promise.all(
        activeSubs.map((s) =>
          updateSubscription.mutateAsync({
            id: s.id,
            data: { status: 'PAUSED' },
          })
        )
      );

      // 2) 거래처 soft-delete
      await deletePartner.mutateAsync(partner.id);

      // 3) 모달 열려 있었다면 닫기
      setSelectedPartner(null);
    } catch (e) {
      console.error('[seller/partners] delete failed:', e);
      alert('삭제에 실패했습니다. 잠시 후 다시 시도해주세요.');
    } finally {
      setDeletePendingId(null);
    }
  };

  // 판매자: 주문 작성 라우트가 별도 페이지로 존재하지 않음
  // (/seller/orders 는 슬라이드 패널 기반) → V1 에서는 빠른 액션 숨김 처리
  const showCreateOrderAction = false;

  const columns: Column<Partner>[] = [
    {
      key: 'is_favorite',
      header: '',
      className: 'w-10',
      render: (item) => (
        <button
          onClick={(e) => {
            e.stopPropagation();
            handleToggleFavorite(item);
          }}
          className="text-gray-300 hover:text-yellow-400"
          aria-label={item.is_favorite ? '즐겨찾기 해제' : '즐겨찾기 등록'}
        >
          <Star
            className={`h-4 w-4 ${item.is_favorite ? 'fill-yellow-400 text-yellow-400' : ''}`}
          />
        </button>
      ),
    },
    {
      key: 'partner_company',
      header: '업체명',
      render: (item) => (
        <div>
          <p className="font-medium text-gray-900">
            {item.nickname || item.partner_company || '-'}
          </p>
          <p className="text-xs text-gray-500">
            {item.partner_name ?? ''}
            {item.nickname && item.partner_company
              ? ` · ${item.partner_company}`
              : ''}
          </p>
        </div>
      ),
    },
    {
      key: 'partner_role',
      header: '유형',
      render: (item) => (
        <span className="text-xs text-gray-500">
          {item.partner_role === 'BUYER' ? '구매자' : '판매자'}
        </span>
      ),
    },
    {
      key: 'created_at',
      header: '등록일',
      render: (item) => (
        <span className="text-sm text-gray-600">
          {formatDate(item.created_at)}
        </span>
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
      render: (item) => (
        <div className="flex items-center justify-end gap-1">
          <button
            onClick={(e) => {
              e.stopPropagation();
              handleStartChat(item);
            }}
            disabled={chatPendingId === item.id || !!chatPendingId}
            title="채팅 시작"
            className="inline-flex items-center gap-1 rounded-lg border border-gray-300 bg-white px-2.5 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            <MessageCircle className="h-3.5 w-3.5" />
            채팅
          </button>
          {showCreateOrderAction && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                router.push(
                  `/seller/orders/new?buyer_id=${item.partner_user_id}`
                );
              }}
              title="주문 작성"
              className="inline-flex items-center gap-1 rounded-lg bg-primary-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-primary-700"
            >
              <FileText className="h-3.5 w-3.5" />
              주문 작성
            </button>
          )}
          <button
            onClick={(e) => {
              e.stopPropagation();
              handleDeletePartner(item);
            }}
            disabled={deletePendingId === item.id || !!deletePendingId}
            title="거래처 삭제"
            aria-label="거래처 삭제"
            className="inline-flex items-center justify-center rounded-lg border border-gray-200 bg-white p-1.5 text-gray-400 hover:border-red-300 hover:bg-red-50 hover:text-red-600 disabled:opacity-50"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-4">
      <PageHeader
        title="거래처 목록"
        description="바이어 거래처를 관리하세요"
        action={
          <button
            onClick={() => setShowAddModal(true)}
            className="inline-flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700"
          >
            <Plus className="h-4 w-4" />
            거래처 추가
          </button>
        }
      />

      {/* V1.6 — 받은 거래처 요청 (수락/거절) */}
      {incomingRequests.length > 0 && (
        <section className="rounded-xl border border-blue-200 bg-blue-50 p-4">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-blue-900">
            <Inbox className="h-4 w-4" />
            받은 거래처 요청 ({incomingRequests.length})
          </h3>
          <ul className="mt-3 space-y-2">
            {incomingRequests.map((p) => (
              <li
                key={p.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-white p-3"
              >
                <div className="min-w-0 flex-1">
                  <p className="font-medium text-gray-900">
                    {p.partner_name ?? '-'}
                  </p>
                  <p className="text-xs text-gray-500">
                    {p.partner_company ?? ''}
                    {p.partner_company && p.partner_role
                      ? ' · '
                      : ''}
                    {p.partner_role === 'BUYER' ? '구매자' : '판매자'}
                  </p>
                </div>
                <div className="flex flex-shrink-0 gap-2">
                  <button
                    type="button"
                    onClick={() => acceptPartner.mutate(p.id)}
                    disabled={acceptPartner.isPending || rejectPartner.isPending}
                    className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                  >
                    수락
                  </button>
                  <button
                    type="button"
                    onClick={() => rejectPartner.mutate(p.id)}
                    disabled={acceptPartner.isPending || rejectPartner.isPending}
                    className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                  >
                    거절
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* V1.6 — 보낸 거래처 요청 (수락 대기 중) */}
      {outgoingRequests.length > 0 && (
        <section className="rounded-xl border border-yellow-200 bg-yellow-50 p-4">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-yellow-900">
            <Clock className="h-4 w-4" />
            보낸 거래처 요청 ({outgoingRequests.length})
          </h3>
          <ul className="mt-3 space-y-2">
            {outgoingRequests.map((p) => (
              <li
                key={p.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-white p-3"
              >
                <div className="min-w-0 flex-1">
                  <p className="font-medium text-gray-900">
                    {p.partner_name ?? '-'}
                  </p>
                  <p className="text-xs text-gray-500">
                    {p.partner_company ?? ''}
                    {p.partner_company && p.partner_role
                      ? ' · '
                      : ''}
                    {p.partner_role === 'BUYER' ? '구매자' : '판매자'}
                  </p>
                </div>
                <div className="flex flex-shrink-0 items-center gap-2">
                  <span className="text-xs text-yellow-700">수락 대기 중</span>
                  <button
                    type="button"
                    onClick={() => {
                      if (window.confirm('이 거래처 요청을 회수하시겠습니까?')) {
                        rejectPartner.mutate(p.id);
                      }
                    }}
                    disabled={rejectPartner.isPending}
                    className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                  >
                    요청 회수
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex-1 min-w-[240px]">
          <SearchFilterBar
            searchValue={search}
            onSearchChange={setSearch}
            searchPlaceholder="거래처명 검색..."
            filters={[
              {
                key: 'status',
                label: '전체 상태',
                options: PARTNER_STATUS_OPTIONS,
                value: statusFilter,
                onChange: setStatusFilter,
              },
            ]}
          />
        </div>
        {/* V1.5 Phase 3: 즐겨찾기만 토글 */}
        <button
          type="button"
          onClick={() => setFavoriteOnly((v) => !v)}
          aria-pressed={favoriteOnly}
          title={favoriteOnly ? '전체 거래처 보기' : '즐겨찾기만 보기'}
          className={`mb-4 inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm font-medium transition-colors ${
            favoriteOnly
              ? 'border-yellow-300 bg-yellow-50 text-yellow-600'
              : 'border-gray-200 bg-white text-gray-500 hover:bg-gray-50'
          }`}
        >
          <Star
            className={`h-4 w-4 ${
              favoriteOnly ? 'fill-yellow-400 text-yellow-400' : ''
            }`}
          />
          즐겨찾기만
        </button>
      </div>

      {isLoading ? (
        <div className="py-12 text-center text-sm text-gray-400">
          로딩 중...
        </div>
      ) : (
        <DataTable
          columns={columns}
          data={visiblePartners}
          onRowClick={(p) => setSelectedPartner(p)}
          emptyMessage={
            favoriteOnly
              ? '즐겨찾기한 거래처가 없습니다.'
              : "등록된 거래처가 없습니다. 우측 상단 '거래처 추가'로 등록하세요."
          }
        />
      )}

      <AddPartnerModal
        isOpen={showAddModal}
        onClose={() => setShowAddModal(false)}
        myRole="SELLER"
      />

      <PartnerDetailModal
        partner={selectedPartner}
        myRole="SELLER"
        onClose={() => setSelectedPartner(null)}
        onDelete={handleDeletePartner}
        deletePending={!!deletePendingId}
      />
    </div>
  );
}
