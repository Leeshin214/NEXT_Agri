'use client';

import { useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type {
  Partner,
  PartnerCreate,
  PartnerStats,
  PartnerStatus,
  SuccessResponse,
} from '@/types';

interface PartnerFilters {
  partner_status?: string;
  search?: string;
  /**
   * PM Report #8 작업 5 (V1.7) — last_trade_date / last_trade_amount 응답에 포함 여부.
   * 백엔드 GET /partners 는 기본 false (성능 보호) — 거래처 페이지에서만 true 로 호출한다.
   * 다른 페이지(orders 정기배송 매핑, 회원 검색의 partner status map 등)는 last_trade
   * 가 필요 없으므로 추가 쿼리 비용을 발생시키지 않도록 false 유지.
   */
  include_last_trade?: boolean;
  page?: number;
  limit?: number;
}

export function usePartners(filters?: PartnerFilters) {
  return useQuery({
    queryKey: ['partners', filters],
    queryFn: () =>
      api.get<SuccessResponse<Partner[]>>('/partners', filters as Record<string, unknown>),
  });
}

export function useCreatePartner() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: PartnerCreate) =>
      api.post<SuccessResponse<Partner>>('/partners', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['partners'] });
    },
  });
}

export function useUpdatePartner() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      data,
    }: {
      id: string;
      data: Record<string, unknown>;
    }) => api.patch<SuccessResponse<Partner>>(`/partners/${id}`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['partners'] });
    },
  });
}

export function useDeletePartner() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/partners/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['partners'] });
    },
  });
}

// 즐겨찾기 토글 — 내부적으로 PATCH /partners/{id} { is_favorite } 사용
export function useTogglePartnerFavorite() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, is_favorite }: { id: string; is_favorite: boolean }) =>
      api.patch<SuccessResponse<Partner>>(`/partners/${id}`, { is_favorite }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['partners'] });
    },
  });
}

/**
 * V1.6 — 받은 거래처 요청 수락.
 * 본인 row 가 PENDING_INCOMING 이어야 하고, 양쪽 row 가 ACTIVE 로 전환된다.
 */
export function useAcceptPartner() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      api.post<SuccessResponse<Partner>>(`/partners/${id}/accept`, {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['partners'] });
    },
  });
}

/**
 * V1.6 — 받은 거래처 요청 거절.
 * 본인 row 가 PENDING_INCOMING 이어야 하고, 양쪽 row 모두 soft-delete 된다.
 */
export function useRejectPartner() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      api.post<SuccessResponse<{ message: string }>>(`/partners/${id}/reject`, {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['partners'] });
    },
  });
}

// 회원 검색에서 "이미 거래처" 표시용 — 인자 없이 전체 거래처 목록을 받아 partner_user_id Set 반환.
// V1.6: ACTIVE/PENDING_OUTGOING/PENDING_INCOMING 모두 포함되어 "이미 관계 있음" 판단에 사용.
// 백엔드 list_partners 는 status 인자 없이 호출 시 모든 상태를 반환한다(검증 완료).
//
// React Query 캐시 공유: usePartners() 와 동일 queryKey 사용 → 거래처 목록 페이지와 캐시 공유.
export function usePartnerUserIdSet(): Set<string> {
  const { data } = usePartners();
  return useMemo(
    () => new Set((data?.data ?? []).map((p) => p.partner_user_id)),
    [data]
  );
}

/**
 * V1.6 — 회원 검색 카드 등에서 상태별 분기 표시를 위한 Map.
 *
 * Set 으로는 "이미 관계가 있다" 까지만 알 수 있어 분기 UI 가 불가능했으나,
 * 양방향 승인 모델 도입으로 다음 4종 분기가 필요해졌다:
 *   ACTIVE           → "거래처 등록됨" (회색)
 *   PENDING_OUTGOING → "요청 보냄" (노란색)
 *   PENDING_INCOMING → "요청 받음 — 수락" 버튼 (받은 요청 처리)
 *   (없음)            → "거래처 추가" 버튼
 *
 * 백엔드 list_partners 는 status 인자 미전송 시 모든 상태를 반환하므로
 * usePartners() 호출 결과를 그대로 Map<partner_user_id, status> 로 변환.
 */
export function usePartnerStatusMap(): Map<string, PartnerStatus> {
  const { data } = usePartners();
  return useMemo(() => {
    const m = new Map<string, PartnerStatus>();
    for (const p of data?.data ?? []) {
      m.set(p.partner_user_id, p.status);
    }
    return m;
  }, [data]);
}

/**
 * 거래처 거래 통계 조회 (V1.5 Phase 1).
 * - total_orders / total_amount / last_order_date / active_subscriptions
 * - PartnerDetailModal 에서 사용.
 */
export function usePartnerStats(partnerId: string) {
  return useQuery({
    queryKey: ['partner-stats', partnerId],
    queryFn: () =>
      api.get<SuccessResponse<PartnerStats>>(
        `/partners/${partnerId}/stats`
      ),
    enabled: !!partnerId,
  });
}
