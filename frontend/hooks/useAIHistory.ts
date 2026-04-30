'use client';

import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { SuccessResponse } from '@/types';
import { useAuthStore } from '@/store/authStore';
import { useAIChatStore, type AIChatTurn } from '@/store/aiChatStore';

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

/**
 * AI 대화 히스토리 조회 훅.
 *
 * - 기본 limit 100 (대화 cap 과 동일)
 * - 응답을 받으면 useAIChatStore 의 hydrateFromHistory 로 캐시 갱신
 * - DB 응답은 최신순이므로 reverse 해서 오래된순으로 정렬한 뒤 store 에 저장
 * - 같은 세션에서 반복 호출되어도 매번 갱신해 다른 탭의 변경을 따라잡음
 */
export function useAIHistory(limit = 100) {
  const { user } = useAuthStore();

  const query = useQuery({
    queryKey: ['ai-history', limit],
    queryFn: () =>
      api.get<SuccessResponse<AIConversation[]>>(`/ai/history`, { limit }),
    enabled: !!user,
    staleTime: 30_000, // 30초 캐시 유지
  });

  // React Query v5 는 onSuccess 콜백을 제거 — useEffect 로 data 변경 시 hydrate
  useEffect(() => {
    if (!query.data?.data) return;

    // 최신순 → 오래된순 reverse
    const turns: AIChatTurn[] = [...query.data.data]
      .reverse()
      .map((conv) => ({
        id: conv.id,
        prompt: conv.prompt,
        response: conv.response,
        prompt_type: conv.prompt_type,
        created_at: conv.created_at,
        pending: false,
      }));

    useAIChatStore.getState().hydrateFromHistory(turns);
  }, [query.data]);

  return query;
}
