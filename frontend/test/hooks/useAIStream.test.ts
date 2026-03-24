import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useAIStream } from '@/hooks/useAIStream';

describe('useAIStream', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('초기 상태에서 isStreaming은 false이다', () => {
    const { result } = renderHook(() => useAIStream());
    expect(result.current.isStreaming).toBe(false);
    expect(result.current.response).toBe('');
  });

  it('빈 프롬프트를 보내면 스트리밍이 시작되지 않는다', async () => {
    const { result } = renderHook(() => useAIStream());
    await act(async () => {
      result.current.stream('');
    });
    expect(result.current.isStreaming).toBe(false);
  });

  it('reset 호출 시 응답이 초기화된다', () => {
    const { result } = renderHook(() => useAIStream());
    act(() => {
      result.current.reset();
    });
    expect(result.current.response).toBe('');
  });
});
