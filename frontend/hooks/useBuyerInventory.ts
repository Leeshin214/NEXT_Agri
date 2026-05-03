'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type {
  BuyerInventory,
  BuyerInventoryListParams,
  BuyerInventoryUpdatePayload,
  SuccessResponse,
} from '@/types';

/**
 * 구매자 재고 목록.
 * 백엔드 GET /buyer/inventory — meta(페이지네이션) 동봉.
 *
 * - search: 상품명 ilike (PostgREST 임베딩 컬럼)
 * - product_id: 특정 상품 한정
 * - sort_by: recent | quantity | name
 */
export function useBuyerInventoryList(params?: BuyerInventoryListParams) {
  return useQuery({
    queryKey: ['buyer-inventory', params],
    queryFn: () =>
      api.get<SuccessResponse<BuyerInventory[]>>(
        '/buyer/inventory',
        params as Record<string, unknown> | undefined
      ),
  });
}

/** 구매자 재고 단건. */
export function useBuyerInventoryDetail(id: string) {
  return useQuery({
    queryKey: ['buyer-inventory', 'detail', id],
    queryFn: () =>
      api.get<SuccessResponse<BuyerInventory>>(`/buyer/inventory/${id}`),
    enabled: !!id,
  });
}

/** 수량/메모 수정 — 성공 시 list/detail 모두 invalidate. */
export function useUpdateBuyerInventory() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      data,
    }: {
      id: string;
      data: BuyerInventoryUpdatePayload;
    }) =>
      api.patch<SuccessResponse<BuyerInventory>>(
        `/buyer/inventory/${id}`,
        data
      ),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['buyer-inventory'] });
      queryClient.invalidateQueries({
        queryKey: ['buyer-inventory', 'detail', variables.id],
      });
    },
  });
}

/** soft delete (목록 숨김). */
export function useDeleteBuyerInventory() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/buyer/inventory/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['buyer-inventory'] });
    },
  });
}
