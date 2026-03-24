'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { Product, ProductCreate, ProductUpdate, SuccessResponse } from '@/types';

interface ProductFilters {
  category?: string;
  product_status?: string;
  seller_id?: string;
  search?: string;
  page?: number;
  limit?: number;
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
