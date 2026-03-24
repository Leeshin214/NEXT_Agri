'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { Partner, PartnerCreate, SuccessResponse } from '@/types';

interface PartnerFilters {
  partner_status?: string;
  search?: string;
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
