'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type {
  DeliveryDateChange,
  DeliveryDateChangeCreate,
  SuccessResponse,
} from '@/types';

/**
 * 납품일 변경 요청·승인 훅 (2026-04-29 추가).
 *
 * 백엔드 엔드포인트:
 *  - GET    /orders/{order_id}/delivery-date-changes              목록 (시간 역순)
 *  - POST   /orders/{order_id}/delivery-date-changes              제시
 *  - POST   /orders/{order_id}/delivery-date-changes/{id}/accept  수락 → orders.delivery_date 업데이트
 *  - POST   /orders/{order_id}/delivery-date-changes/{id}/reject  거절
 *
 * 상태 가드: 백엔드는 QUOTE_REQUESTED/NEGOTIATING/CONFIRMED 일 때만 변경 요청 허용.
 * PREPARING 이상에서는 422 응답 → mutation onError 에서 사용자 메시지 표시 필요.
 */

export function useDeliveryDateChanges(orderId: string) {
  return useQuery({
    queryKey: ['orders', orderId, 'delivery-date-changes'],
    queryFn: () =>
      api.get<SuccessResponse<DeliveryDateChange[]>>(
        `/orders/${orderId}/delivery-date-changes`
      ),
    enabled: !!orderId,
  });
}

export function useSubmitDeliveryDateChange(orderId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: DeliveryDateChangeCreate) =>
      api.post<SuccessResponse<DeliveryDateChange>>(
        `/orders/${orderId}/delivery-date-changes`,
        payload
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['orders', orderId, 'delivery-date-changes'],
      });
      queryClient.invalidateQueries({ queryKey: ['order', orderId] });
      // 백엔드가 같은 change_id 의 이전 messages.metadata.status 를 SUPERSEDED 로 동기화 →
      // 채팅 메시지 카드의 수락/거절 버튼이 자동 사라지도록 messages 캐시 broad invalidate.
      queryClient.invalidateQueries({ queryKey: ['messages'] });
    },
  });
}

export function useAcceptDeliveryDateChange(orderId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ changeId }: { changeId: string }) =>
      api.post<SuccessResponse<DeliveryDateChange>>(
        `/orders/${orderId}/delivery-date-changes/${changeId}/accept`
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['orders', orderId, 'delivery-date-changes'],
      });
      queryClient.invalidateQueries({ queryKey: ['order', orderId] });
      // 주문 목록 (delivery_date 컬럼 갱신)
      queryClient.invalidateQueries({ queryKey: ['orders'] });
      // 캘린더 동기화 — 수락된 새 납품일이 캘린더 이벤트로 반영됨
      queryClient.invalidateQueries({ queryKey: ['calendar'] });
      // 채팅 메시지 metadata.status 동기화 (PENDING → ACCEPTED) → 카드 버튼 자동 제거
      queryClient.invalidateQueries({ queryKey: ['messages'] });
    },
  });
}

export function useRejectDeliveryDateChange(orderId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ changeId }: { changeId: string }) =>
      api.post<SuccessResponse<DeliveryDateChange>>(
        `/orders/${orderId}/delivery-date-changes/${changeId}/reject`
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['orders', orderId, 'delivery-date-changes'],
      });
      queryClient.invalidateQueries({ queryKey: ['order', orderId] });
      // 채팅 메시지 metadata.status 동기화 (PENDING → REJECTED) → 카드 버튼 자동 제거
      queryClient.invalidateQueries({ queryKey: ['messages'] });
    },
  });
}
