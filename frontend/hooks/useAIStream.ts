'use client';

import { useState, useCallback, useRef } from 'react';
import { createClient } from '@/lib/supabase/client';

export function useAIStream() {
  const [response, setResponse] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
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
        setResponse((json.data as Record<string, unknown>).response as string);
      } else {
        setResponse('AI 응답 형식이 올바르지 않습니다.');
      }
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        setResponse('AI 응답을 받는 중 오류가 발생했습니다. 다시 시도해주세요.');
      }
    } finally {
      setIsStreaming(false);
    }
  }, [isStreaming]);

  const abort = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const reset = useCallback(() => {
    setResponse('');
  }, []);

  return { response, isStreaming, stream, abort, reset };
}
