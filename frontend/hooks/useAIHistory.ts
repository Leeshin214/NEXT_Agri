'use client';

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { SuccessResponse } from '@/types';
import { useAuthStore } from '@/store/authStore';

// 백엔드 AIConversationResponse 스키마에 맞춤
// (prompt/response 필드 — user_message/ai_response 아님)
export interface AIConversation {
  id: string;
  user_id: string;
  prompt: string;
  response: string;
  prompt_type: string | null;
  created_at: string;
}

export function useAIHistory(limit = 50) {
  const { user } = useAuthStore();

  return useQuery({
    queryKey: ['ai-history', limit],
    queryFn: () =>
      api.get<SuccessResponse<AIConversation[]>>(`/ai/history`, { limit }),
    enabled: !!user,
    staleTime: 30_000, // 30초 캐시 유지
  });
}
