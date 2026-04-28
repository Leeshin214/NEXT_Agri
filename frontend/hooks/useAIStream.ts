'use client';

import { useState, useCallback, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { createClient } from '@/lib/supabase/client';

export function useAIStream() {
  const queryClient = useQueryClient();
  const [response, setResponse] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [manualReview, setManualReview] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const stream = useCallback(async (prompt: string, promptType?: string) => {
    if (!prompt.trim() || isStreaming) return;

    setResponse('');
    setIsStreaming(true);

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
        const data = json.data as Record<string, unknown>;
        setResponse(data.response as string);
        // manual_review 플래그 추출 — orchestrator가 검증 실패 시 true로 반환
        setManualReview(data.manual_review === true);
      } else {
        setResponse('AI 응답 형식이 올바르지 않습니다.');
        setManualReview(false);
      }
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        setResponse('AI 응답을 받는 중 오류가 발생했습니다. 다시 시도해주세요.');
      }
      setManualReview(false);
    } finally {
      setIsStreaming(false);
      // AI 대화가 백엔드에 저장된 직후이므로 히스토리 캐시 무효화
      // (AbortError 포함 모든 종료 경로에서 호출 — staleTime 30s 캐시 즉시 갱신)
      // queryKey: ['ai-history', limit] — useAIHistory.ts 와 동일
      queryClient.invalidateQueries({ queryKey: ['ai-history'] });
    }
  }, [isStreaming, queryClient]);

  const abort = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const reset = useCallback(() => {
    setResponse('');
    setManualReview(false);
  }, []);

  return { response, isStreaming, manualReview, stream, abort, reset };
}
