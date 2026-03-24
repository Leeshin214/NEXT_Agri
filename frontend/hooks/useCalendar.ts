'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { CalendarEvent, CalendarEventCreate, SuccessResponse } from '@/types';

export function useCalendarEvents(year: number, month: number) {
  return useQuery({
    queryKey: ['calendar', year, month],
    queryFn: () =>
      api.get<SuccessResponse<CalendarEvent[]>>('/calendar', { year, month }),
  });
}

export function useCreateCalendarEvent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: CalendarEventCreate) =>
      api.post<SuccessResponse<CalendarEvent>>('/calendar', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['calendar'] });
    },
  });
}

export function useDeleteCalendarEvent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/calendar/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['calendar'] });
    },
  });
}
