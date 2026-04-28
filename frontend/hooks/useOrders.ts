'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type {
  CounterOffer,
  CounterOfferCreate,
  Order,
  OrderCreate,
  OrderStatus,
  OrderUpdate,
  SuccessResponse,
} from '@/types';

interface OrderFilters {
  order_status?: OrderStatus;
  /**
   * 다중 상태 필터 — 백엔드 GET /orders 의 status_in 다중값 query 와 매핑.
   * lib/api.ts 의 paramsSerializer 가 ?status_in=A&status_in=B (repeat) 형태로 직렬화한다.
   */
  status_in?: OrderStatus[];
  page?: number;
  limit?: number;
}

/**
 * V1.6 — 주문 목록 조회.
 *
 * `enabled` 옵션:
 *   - 정기배송 탭처럼 일반 주문을 가져올 필요가 없을 때 false 로 비활성화한다.
 *   - 미지정 시 기본 true (쿼리 활성).
 *   - status_in 이 빈 배열인 경우에도 자동 비활성화 — `?` 쿼리만 붙은 채 모든 주문을
 *     가져오는 사고를 방지.
 */
export function useOrders(
  filters?: OrderFilters,
  options?: { enabled?: boolean }
) {
  const isEmptyStatusIn =
    filters?.status_in !== undefined && filters.status_in.length === 0;
  const enabled = (options?.enabled ?? true) && !isEmptyStatusIn;
  return useQuery({
    queryKey: ['orders', filters],
    queryFn: () =>
      api.get<SuccessResponse<Order[]>>('/orders', filters as Record<string, unknown>),
    enabled,
  });
}

export function useOrder(id: string) {
  return useQuery({
    queryKey: ['order', id],
    queryFn: () => api.get<SuccessResponse<Order>>(`/orders/${id}`),
    enabled: !!id,
  });
}

export function useCreateOrder() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: OrderCreate) =>
      api.post<SuccessResponse<Order>>('/orders', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['orders'] });
    },
  });
}

export function useUpdateOrder(orderId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: OrderUpdate) =>
      api.patch<SuccessResponse<Order>>(`/orders/${orderId}`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['orders'] });
      queryClient.invalidateQueries({ queryKey: ['order', orderId] });
    },
  });
}

export function useUpdateOrderStatus() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: OrderStatus }) =>
      api.patch<SuccessResponse<Order>>(`/orders/${id}/status`, { status }),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['orders'] });
      queryClient.invalidateQueries({ queryKey: ['order', variables.id] });
    },
  });
}

export function useCancelOrder(orderId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ reason }: { reason: string }) =>
      api.patch<SuccessResponse<Order>>(`/orders/${orderId}/cancel`, { reason }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['orders'] });
      queryClient.invalidateQueries({ queryKey: ['order', orderId] });
    },
  });
}

export function useSubmitCounterOffer(orderId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CounterOfferCreate) =>
      api.post<SuccessResponse<CounterOffer>>(
        `/orders/${orderId}/counter-offers`,
        payload
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['orders'] });
      queryClient.invalidateQueries({ queryKey: ['order', orderId] });
      queryClient.invalidateQueries({ queryKey: ['negotiation', orderId] });
      // 백엔드가 같은 offer_id 의 이전 messages.metadata.status 를 SUPERSEDED 로 동기화하므로
      // 채팅 메시지 목록도 refetch 해야 이전 카드의 수락/거절 버튼이 사라진다.
      // roomId 를 모르므로 broad 하게 ['messages'] 로 invalidate.
      queryClient.invalidateQueries({ queryKey: ['messages'] });
    },
  });
}

export function useAcceptCounterOffer(orderId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ offerId }: { offerId: string }) =>
      api.post<SuccessResponse<CounterOffer>>(
        `/orders/${orderId}/counter-offers/${offerId}/accept`
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['orders'] });
      queryClient.invalidateQueries({ queryKey: ['order', orderId] });
      queryClient.invalidateQueries({ queryKey: ['negotiation', orderId] });
      // 수락 시 백엔드가 해당 offer_id 의 messages.metadata.status 를 ACCEPTED 로 동기화 →
      // 이전 카드의 수락/거절 버튼을 자동으로 사라지게 하려면 messages 캐시도 refetch 필요.
      queryClient.invalidateQueries({ queryKey: ['messages'] });
    },
  });
}

export function useRejectCounterOffer(orderId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ offerId }: { offerId: string }) =>
      api.post<SuccessResponse<CounterOffer>>(
        `/orders/${orderId}/counter-offers/${offerId}/reject`
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['orders'] });
      queryClient.invalidateQueries({ queryKey: ['order', orderId] });
      queryClient.invalidateQueries({ queryKey: ['negotiation', orderId] });
      // 거절 시 messages.metadata.status 를 REJECTED 로 동기화 → 동일.
      queryClient.invalidateQueries({ queryKey: ['messages'] });
    },
  });
}

export function useNegotiationHistory(orderId: string) {
  return useQuery({
    queryKey: ['negotiation', orderId],
    queryFn: () =>
      api.get<SuccessResponse<CounterOffer[]>>(
        `/orders/${orderId}/counter-offers`
      ),
    enabled: !!orderId,
  });
}
