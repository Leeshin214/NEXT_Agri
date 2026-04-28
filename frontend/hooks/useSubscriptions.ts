'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type {
  Subscription,
  SubscriptionCreate,
  SubscriptionUpdate,
  SuccessResponse,
} from '@/types';

interface SubscriptionFilters {
  status?: string;
  partner_user_id?: string;
  page?: number;
  limit?: number;
}

/**
 * 내 정기배송 목록 조회 (buyer 또는 seller 측 모두).
 * filters.status / filters.partner_user_id 가 변경되면 자동 refetch.
 *
 * `enabled` 옵션 — 명시적으로 false 를 전달해 비활성화 가능.
 * 정기배송 탭이 비활성인 페이지에서 불필요한 fetch 를 막을 때 사용.
 */
export function useSubscriptions(
  filters?: SubscriptionFilters,
  options?: { enabled?: boolean }
) {
  const enabled = options?.enabled ?? true;
  return useQuery({
    queryKey: ['subscriptions', filters],
    queryFn: () =>
      api.get<SuccessResponse<Subscription[]>>(
        '/subscriptions',
        filters as Record<string, unknown>
      ),
    enabled,
  });
}

export function useSubscription(id: string) {
  return useQuery({
    queryKey: ['subscription', id],
    queryFn: () =>
      api.get<SuccessResponse<Subscription>>(`/subscriptions/${id}`),
    enabled: !!id,
  });
}

export function useCreateSubscription() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: SubscriptionCreate) =>
      api.post<SuccessResponse<Subscription>>('/subscriptions', data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['subscriptions'] });
      qc.invalidateQueries({ queryKey: ['partner-stats'] });
    },
  });
}

export function useUpdateSubscription(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: SubscriptionUpdate) =>
      api.patch<SuccessResponse<Subscription>>(
        `/subscriptions/${id}`,
        data
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['subscriptions'] });
      qc.invalidateQueries({ queryKey: ['subscription', id] });
      qc.invalidateQueries({ queryKey: ['partner-stats'] });
    },
  });
}

/**
 * id 가 동적으로 결정되는 상황(거래처 삭제 시 활성 정기배송을 일괄 PAUSED 처리 등)을 위한
 * 일반화된 update 훅.
 *
 * `useUpdateSubscription(id)` 는 컴포넌트 마운트 시점에 id 가 고정되어야 하므로
 * Promise.all 로 여러 개를 동시에 update 하기 어렵다.
 * 본 훅은 mutateAsync({ id, data }) 형태로 호출하여 동적 id 에 대응한다.
 */
export function useUpdateSubscriptionGeneric() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      data,
    }: {
      id: string;
      data: SubscriptionUpdate;
    }) =>
      api.patch<SuccessResponse<Subscription>>(
        `/subscriptions/${id}`,
        data
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['subscriptions'] });
      qc.invalidateQueries({ queryKey: ['partner-stats'] });
    },
  });
}

export function useDeleteSubscription() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      api.delete<SuccessResponse<{ deleted: boolean }>>(
        `/subscriptions/${id}`
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['subscriptions'] });
      qc.invalidateQueries({ queryKey: ['partner-stats'] });
    },
  });
}

/**
 * 이번 회차 주문 생성 — 정기배송에서 한 회차 주문을 즉시 생성한다.
 * subscription.next_delivery_date 가 자동으로 다음 회차로 갱신되므로
 * subscriptions / orders / calendar 쿼리를 모두 무효화.
 */
export function useGenerateSubscriptionOrder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      api.post<SuccessResponse<{ id: string; order_number?: string }>>(
        `/subscriptions/${id}/generate-order`,
        {}
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['subscriptions'] });
      qc.invalidateQueries({ queryKey: ['orders'] });
      qc.invalidateQueries({ queryKey: ['calendar'] });
    },
  });
}

/**
 * V1.6 — PENDING 정기배송 수락.
 * created_by 가 본인이 아닌 사용자만 호출 가능 (백엔드 가드).
 * status='ACTIVE' 로 전환되며, 캘린더에 가상 이벤트가 즉시 표시된다.
 */
export function useAcceptSubscription() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      api.post<SuccessResponse<Subscription>>(
        `/subscriptions/${id}/accept`,
        {}
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['subscriptions'] });
      qc.invalidateQueries({ queryKey: ['partner-stats'] });
      qc.invalidateQueries({ queryKey: ['calendar'] });
    },
  });
}

/**
 * V1.6 — PENDING 정기배송 거절. status='REJECTED' 로 전환.
 */
export function useRejectSubscription() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      api.post<SuccessResponse<{ message: string }>>(
        `/subscriptions/${id}/reject`,
        {}
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['subscriptions'] });
      qc.invalidateQueries({ queryKey: ['partner-stats'] });
    },
  });
}
