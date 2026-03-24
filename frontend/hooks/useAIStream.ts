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

      const res = await fetch(`${apiUrl}/api/v1/ai/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ prompt, prompt_type: promptType }),
        signal: abortRef.current.signal,
      });

      const reader = res.body?.getReader();
      if (!reader) return;

      const decoder = new TextDecoder();
      let accumulated = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split('\n');

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const text = line.slice(6);
            if (text === '[DONE]') break;
            accumulated += text;
            setResponse(accumulated);
          }
        }
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
