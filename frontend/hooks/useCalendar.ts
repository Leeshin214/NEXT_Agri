'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { CalendarEvent, CalendarEventCreate, SuccessResponse } from '@/types';

/**
 * 캘린더 일정 조회.
 * - year/month 둘 다 전달: 그 월에 한정된 일정 반환 (캘린더 그리드용)
 * - 인자 없거나 둘 다 undefined: 사용자의 모든 active 일정 반환 (전체 일정 리스트용)
 *
 * 백엔드 GET /calendar 는 year/month 모두 Optional. lib/api.ts paramsSerializer 가
 * undefined 값을 자동으로 빈 query 로 처리해주므로 그대로 전달해도 안전하다.
 */
export function useCalendarEvents(year?: number, month?: number) {
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
