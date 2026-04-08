import { useMutation } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { SuccessResponse } from '@/types/api';
import type { ScheduleRecommendResponse } from '@/types/scheduleAgent';

export function useScheduleRecommend() {
  return useMutation({
    mutationFn: async (params: { year: number; month: number }) => {
      const res = await api.post<SuccessResponse<ScheduleRecommendResponse>>(
        '/schedule-agent/recommend',
        params
      );
      return res;
    },
  });
}
