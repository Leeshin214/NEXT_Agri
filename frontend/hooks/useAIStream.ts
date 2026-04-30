'use client';

import { useState, useCallback, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { createClient } from '@/lib/supabase/client';
import { useAIChatStore } from '@/store/aiChatStore';

/**
 * useAIStream — AI 에이전트 채팅 호출 + 응답 상태 관리.
 *
 * 응답이 도착하면 useAIChatStore 에 turn 형태로 저장되어 페이지를 떠났다가
 * 돌아와도 화면에 그대로 남는다. response/abort/reset 은 외부 호환성으로 유지.
 */
export function useAIStream() {
  const queryClient = useQueryClient();
  const [response, setResponse] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [manualReview, setManualReview] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const stream = useCallback(
    async (prompt: string, promptType?: string) => {
      if (!prompt.trim() || isStreaming) return;

      // 1. 스토어에 pending turn 추가 — 사용자 메시지 즉시 표시
      const tempId = useAIChatStore
        .getState()
        .addPendingTurn(prompt, promptType ?? null);

      setResponse('');
      setIsStreaming(true);
      setManualReview(false);

      try {
        abortRef.current = new AbortController();
        const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

        const supabase = createClient();
        const { data } = await supabase.auth.getSession();
        const token = data.session?.access_token;

        const res = await fetch(`${apiUrl}/api/v1/ai/agent/chat`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({ prompt, prompt_type: promptType }),
          signal: abortRef.current.signal,
        });

        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }

        const json: unknown = await res.json();

        if (
          json !== null &&
          typeof json === 'object' &&
          'data' in json &&
          json.data !== null &&
          typeof json.data === 'object' &&
          'response' in json.data &&
          typeof (json.data as Record<string, unknown>).response === 'string'
        ) {
          const dataObj = json.data as Record<string, unknown>;
          const finalResponse = dataObj.response as string;
          const isManualReview = dataObj.manual_review === true;

          setResponse(finalResponse);
          setManualReview(isManualReview);

          // 백엔드 응답에 id/created_at 이 있으면 사용, 없으면 tempId/기존값 유지
          const finalId = typeof dataObj.id === 'string' ? dataObj.id : undefined;
          const finalCreatedAt =
            typeof dataObj.created_at === 'string' ? dataObj.created_at : undefined;

          useAIChatStore.getState().resolveTurn(tempId, {
            id: finalId,
            response: finalResponse,
            created_at: finalCreatedAt,
          });
        } else {
          const errMsg = 'AI 응답 형식이 올바르지 않습니다.';
          setResponse(errMsg);
          setManualReview(false);
          useAIChatStore.getState().failTurn(tempId, errMsg);
        }
      } catch (err) {
        const isAbort = (err as Error).name === 'AbortError';
        const errMsg = isAbort
          ? '응답이 취소되었습니다.'
          : 'AI 응답을 받는 중 오류가 발생했습니다. 다시 시도해주세요.';
        if (!isAbort) {
          setResponse(errMsg);
        }
        setManualReview(false);
        useAIChatStore.getState().failTurn(tempId, errMsg);
      } finally {
        setIsStreaming(false);
        // 백그라운드 동기화 — DB 의 정식 id/created_at 이 다음 hydrate 때 반영되도록
        queryClient.invalidateQueries({ queryKey: ['ai-history'] });
      }
    },
    [isStreaming, queryClient]
  );

  const abort = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const reset = useCallback(() => {
    setResponse('');
    setManualReview(false);
  }, []);

  return { response, isStreaming, manualReview, stream, abort, reset };
}
