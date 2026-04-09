'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { createClient } from '@/lib/supabase/client';

export interface WebSocketMessage {
  type: 'message' | 'error';
  id?: string;
  room_id?: string;
  sender_id?: string;
  content?: string;
  is_read?: boolean;
  created_at?: string;
  deleted_at?: string | null;
  message?: string; // error type일 때
}

const WS_BASE_URL =
  process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000';

const MAX_RETRY = 3;
const RETRY_DELAY_MS = 3000;

export function useWebSocketChat(roomId: string | null): {
  isConnected: boolean;
  sendMessage: (content: string) => void;
  lastMessage: WebSocketMessage | null;
  error: string | null;
} {
  const [isConnected, setIsConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null);
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const retryCountRef = useRef(0);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // roomId가 언마운트 시 클린업에서도 참조 가능하도록 ref로 보관
  const roomIdRef = useRef(roomId);

  useEffect(() => {
    roomIdRef.current = roomId;
  }, [roomId]);

  const connect = useCallback(async () => {
    if (!roomIdRef.current) return;

    // 기존 연결 정리
    if (wsRef.current) {
      wsRef.current.onclose = null; // 재연결 루프 방지
      wsRef.current.close();
      wsRef.current = null;
    }

    let token: string | null = null;
    try {
      const supabase = createClient();
      const {
        data: { session },
      } = await supabase.auth.getSession();
      token = session?.access_token ?? null;
    } catch {
      setError('인증 토큰을 가져올 수 없습니다.');
      return;
    }

    // 토큰 없으면 연결하지 않음 (백엔드 code 4001 즉시 종료 방지)
    if (!token) {
      setError('인증 토큰이 없어 WebSocket에 연결할 수 없습니다.');
      return;
    }

    const url = `${WS_BASE_URL}/ws/chat/${roomIdRef.current}?token=${token}`;

    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch {
      setError('WebSocket 연결을 초기화할 수 없습니다.');
      return;
    }

    wsRef.current = ws;

    ws.onopen = () => {
      setIsConnected(true);
      setError(null);
      retryCountRef.current = 0;
    };

    ws.onmessage = (event: MessageEvent) => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(event.data as string);
      } catch {
        setError('서버로부터 잘못된 메시지 형식을 수신했습니다.');
        return;
      }

      if (
        typeof parsed === 'object' &&
        parsed !== null &&
        'type' in parsed &&
        (parsed as { type: unknown }).type === 'message'
      ) {
        setLastMessage(parsed as WebSocketMessage);
      } else if (
        typeof parsed === 'object' &&
        parsed !== null &&
        'type' in parsed &&
        (parsed as { type: unknown }).type === 'error'
      ) {
        const errMsg = (parsed as WebSocketMessage).message ?? '알 수 없는 오류가 발생했습니다.';
        setError(errMsg);
      }
    };

    ws.onerror = () => {
      setIsConnected(false);
    };

    ws.onclose = (event) => {
      setIsConnected(false);
      wsRef.current = null;

      // 인증 실패(4001)이면 재시도하지 않음
      if (event.code === 4001) {
        setError('인증에 실패하여 채팅 연결이 종료되었습니다.');
        return;
      }

      // roomId가 여전히 유효하고 최대 재시도 횟수 미만이면 재연결
      if (roomIdRef.current && retryCountRef.current < MAX_RETRY) {
        retryCountRef.current += 1;
        retryTimerRef.current = setTimeout(() => {
          connect();
        }, RETRY_DELAY_MS);
      } else if (retryCountRef.current >= MAX_RETRY) {
        setError('서버 연결에 실패했습니다. 페이지를 새로고침해주세요.');
      }
    };
  }, []); // connect 자체는 roomIdRef를 사용하므로 deps 없음

  useEffect(() => {
    if (!roomId) {
      // roomId가 null로 바뀌면 기존 연결 정리
      if (retryTimerRef.current) {
        clearTimeout(retryTimerRef.current);
        retryTimerRef.current = null;
      }
      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.close();
        wsRef.current = null;
      }
      setIsConnected(false);
      setLastMessage(null);
      setError(null);
      retryCountRef.current = 0;
      return;
    }

    // roomId가 변경되면 재연결
    retryCountRef.current = 0;
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
    connect();

    return () => {
      // 언마운트 또는 roomId 변경 시 정리
      if (retryTimerRef.current) {
        clearTimeout(retryTimerRef.current);
        retryTimerRef.current = null;
      }
      if (wsRef.current) {
        wsRef.current.onclose = null; // 재연결 루프 방지
        wsRef.current.close();
        wsRef.current = null;
      }
      setIsConnected(false);
    };
  }, [roomId, connect]);

  const sendMessage = useCallback((content: string) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      setError('WebSocket이 연결되어 있지 않습니다.');
      return;
    }
    try {
      wsRef.current.send(JSON.stringify({ type: 'message', content }));
    } catch {
      setError('메시지 전송 중 오류가 발생했습니다.');
    }
  }, []);

  return { isConnected, sendMessage, lastMessage, error };
}
