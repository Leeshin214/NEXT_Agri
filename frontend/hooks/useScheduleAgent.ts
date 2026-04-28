import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { SuccessResponse } from '@/types/api';
import type { ScheduleRecommendResponse } from '@/types/scheduleAgent';

/**
 * AI 일정 추천 mutation.
 *
 * 백엔드가 추천 결과를 calendar_events 에 INSERT 하므로 (또는 추후 INSERT 할 수 있으므로)
 * 성공 시 ['calendar'] 쿼리를 invalidate 해 캘린더 그리드와 우측 리스트가 즉시 반영되게 한다.
 * 단순 추천만 반환하고 INSERT 가 없는 케이스에서도 invalidate 비용은 무시 가능.
 */
export function useScheduleRecommend() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (params: { year: number; month: number }) => {
      const res = await api.post<SuccessResponse<ScheduleRecommendResponse>>(
        '/schedule-agent/recommend',
        params
      );
      return res;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['calendar'] });
    },
  });
}
