'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { Order, OrderCreate, OrderStatus, SuccessResponse } from '@/types';

interface OrderFilters {
  order_status?: OrderStatus;
  page?: number;
  limit?: number;
}

export function useOrders(filters?: OrderFilters) {
  return useQuery({
    queryKey: ['orders', filters],
    queryFn: () =>
      api.get<SuccessResponse<Order[]>>('/orders', filters as Record<string, unknown>),
  });
}

export function useOrder(id: string) {
  return useQuery({
    queryKey: ['orders', id],
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

export function useUpdateOrderStatus() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: OrderStatus }) =>
      api.patch<SuccessResponse<Order>>(`/orders/${id}/status`, { status }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['orders'] });
    },
  });
}
