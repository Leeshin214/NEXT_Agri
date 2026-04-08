'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { createClient } from '@/lib/supabase/client';
import { api } from '@/lib/api';
import type { ChatRoom, Message, SuccessResponse } from '@/types';
import { useWebSocketChat } from './useWebSocketChat';

// ─── 채팅방 목록 (Realtime 구독으로 자동 갱신) ───

export function useChatRooms() {
  const queryClient = useQueryClient();
  const supabase = createClient();

  const query = useQuery({
    queryKey: ['chatRooms'],
    queryFn: () => api.get<SuccessResponse<ChatRoom[]>>('/chat/rooms'),
  });

  useEffect(() => {
    const channel = supabase
      .channel('chat-rooms-realtime')
      .on(
        'postgres_changes',
        { event: 'UPDATE', schema: 'public', table: 'chat_rooms' },
        () => {
          queryClient.invalidateQueries({ queryKey: ['chatRooms'] });
        }
      )
      .on(
        'postgres_changes',
        { event: 'INSERT', schema: 'public', table: 'chat_rooms' },
        () => {
          queryClient.invalidateQueries({ queryKey: ['chatRooms'] });
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [queryClient, supabase]);

  return query;
}

// ─── 메시지 목록 (Realtime 구독으로 실시간 메시지 수신) ───

export function useMessages(roomId: string) {
  const queryClient = useQueryClient();
  const supabase = createClient();

  const query = useQuery({
    queryKey: ['messages', roomId],
    queryFn: () =>
      api.get<SuccessResponse<Message[]>>(`/chat/rooms/${roomId}/messages`),
    enabled: !!roomId,
  });

  useEffect(() => {
    if (!roomId) return;

    const channel = supabase
      .channel(`room:${roomId}`)
      .on(
        'postgres_changes',
        {
          event: 'INSERT',
          schema: 'public',
          table: 'messages',
          filter: `room_id=eq.${roomId}`,
        },
        (payload) => {
          const newMessage = payload.new as Message;
          queryClient.setQueryData(
            ['messages', roomId],
            (old: SuccessResponse<Message[]> | undefined) => {
              if (!old) return { data: [newMessage] };
              const exists = old.data.some((m) => m.id === newMessage.id);
              if (exists) return old;
              return { ...old, data: [...old.data, newMessage] };
            }
          );
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [roomId, queryClient, supabase]);

  return query;
}

// ─── 메시지 목록 + WebSocket 실시간 송수신 통합 훅 ───
// 초기 메시지 로드: REST API (기존 useMessages 동일)
// 실시간 수신: WebSocket lastMessage → React Query 캐시에 즉시 반영
// 메시지 전송: WebSocket sendMessage 사용 (REST API 대신)

export function useMessagesWithWebSocket(roomId: string | null) {
  const queryClient = useQueryClient();

  // 초기 메시지 로드 (REST API)
  const messageQuery = useQuery({
    queryKey: ['messages', roomId],
    queryFn: () =>
      api.get<SuccessResponse<Message[]>>(`/chat/rooms/${roomId}/messages`),
    enabled: !!roomId,
  });

  // WebSocket 연결
  const { isConnected, sendMessage: wsSendMessage, lastMessage, error: wsError } =
    useWebSocketChat(roomId);

  // WebSocket으로 수신한 메시지를 React Query 캐시에 즉시 반영
  useEffect(() => {
    if (!lastMessage || lastMessage.type !== 'message' || !roomId) return;
    if (
      !lastMessage.id ||
      !lastMessage.sender_id ||
      lastMessage.content === undefined ||
      lastMessage.is_read === undefined ||
      !lastMessage.created_at
    ) {
      return;
    }

    const incomingMessage: Message = {
      id: lastMessage.id,
      room_id: lastMessage.room_id ?? roomId,
      sender_id: lastMessage.sender_id,
      content: lastMessage.content,
      is_read: lastMessage.is_read,
      created_at: lastMessage.created_at,
    };

    queryClient.setQueryData(
      ['messages', roomId],
      (old: SuccessResponse<Message[]> | undefined) => {
        if (!old) return { data: [incomingMessage] };
        const exists = old.data.some((m) => m.id === incomingMessage.id);
        if (exists) return old;
        return { ...old, data: [...old.data, incomingMessage] };
      }
    );

    // 채팅방 목록의 last_message도 갱신
    queryClient.invalidateQueries({ queryKey: ['chatRooms'] });
  }, [lastMessage, roomId, queryClient]);

  return {
    messageQuery,
    isConnected,
    sendMessage: wsSendMessage,
    wsError,
  };
}

// ─── 메시지 전송 ───

export function useSendMessage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ roomId, content }: { roomId: string; content: string }) =>
      api.post<SuccessResponse<Message>>(`/chat/rooms/${roomId}/messages`, {
        content,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['chatRooms'] });
    },
  });
}

// ─── 채팅방 생성 ───

export function useCreateChatRoom() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: { partner_user_id: string; order_id?: string }) =>
      api.post<SuccessResponse<ChatRoom>>('/chat/rooms', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['chatRooms'] });
    },
  });
}

// ─── 읽음 처리 ───

export function useMarkAsRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (roomId: string) =>
      api.post(`/chat/rooms/${roomId}/read`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['chatRooms'] });
    },
  });
}

// ─── AI 채팅 요약 ───

export function useSummarizeChat() {
  return useMutation({
    mutationFn: (messages: string) =>
      api.post<SuccessResponse<{ summary: string }>>('/ai/summarize-chat', {
        messages,
        context: '농산물 유통 거래 채팅',
      }),
  });
}
