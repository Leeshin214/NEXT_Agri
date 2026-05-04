'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type {
  Product,
  ProductCreate,
  ProductDetailResponse,
  ProductUpdate,
  SuccessResponse,
} from '@/types';

interface ProductFilters {
  category?: string;
  product_status?: string;
  seller_id?: string;
  search?: string;
  page?: number;
  limit?: number;
  max_price?: number;
  min_stock?: number;
}

export function useProducts(filters?: ProductFilters) {
  return useQuery({
    queryKey: ['products', filters],
    queryFn: () =>
      api.get<SuccessResponse<Product[]>>('/products', filters as Record<string, unknown>),
  });
}

export function useProduct(id: string) {
  return useQuery({
    queryKey: ['products', id],
    queryFn: () => api.get<SuccessResponse<Product>>(`/products/${id}`),
    enabled: !!id,
  });
}

/**
 * 상품 상세 페이지 전용 — 판매자 join + 거래 관계 + 같은 판매자 다른 상품 포함.
 * 백엔드 GET /products/{id}/detail (B.1, 2026-05-04) 응답을 그대로 반환.
 *
 * 사용처:
 *   - /buyer/browse/[productId]/page.tsx — 상세 페이지 본문
 *   - components/chat/ChatRoomInquiryProduct.tsx — 채팅 헤더 미니카드
 *
 * 캐시 키는 ['products', id, 'detail'] — 기존 useProduct(['products', id]) 와 분리해
 * 단순 응답을 가져가는 다른 화면과 캐시 충돌이 없게 한다.
 */
export function useProductDetail(id: string | null | undefined) {
  return useQuery({
    queryKey: ['products', id, 'detail'],
    queryFn: () =>
      api.get<SuccessResponse<ProductDetailResponse>>(
        `/products/${id}/detail`
      ),
    enabled: !!id,
  });
}

export function useCreateProduct() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: ProductCreate) =>
      api.post<SuccessResponse<Product>>('/products', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['products'] });
    },
  });
}

export function useUpdateProduct() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: ProductUpdate }) =>
      api.patch<SuccessResponse<Product>>(`/products/${id}`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['products'] });
    },
  });
}

export function useDeleteProduct() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/products/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['products'] });
    },
  });
}
