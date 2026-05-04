'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { createClient } from '@/lib/supabase/client';
import { api } from '@/lib/api';
import type {
  ChatRoom,
  CounterOffer,
  CounterOfferCreate,
  Message,
  MessageType,
  NegotiationDraft,
  SuccessResponse,
} from '@/types';
import { useWebSocketChat } from './useWebSocketChat';
import { useAuthStore } from '@/store/authStore';

// 협상/주문 캐시까지 invalidate 해야 하는 message_type 들
// (백엔드 order_service._emit_chat_event 가 broadcast 하는 type 들)
const ORDER_RELATED_TYPES: MessageType[] = [
  'COUNTER_OFFER',
  'OFFER_ACCEPTED',
  'OFFER_REJECTED',
  'ORDER_STATUS',
  'ORDER_CANCELLED',
  // SYSTEM 은 견적 요청 자동 생성 시 발송 → 신규 주문이 목록에 노출되도록 invalidate
  'SYSTEM',
  // 납품일 변경 — 수락 시 orders.delivery_date / 캘린더 동기화 반영 필요
  'DELIVERY_DATE_CHANGE',
  'DELIVERY_DATE_ACCEPTED',
  'DELIVERY_DATE_REJECTED',
];

// ─── 채팅방 목록 (Realtime 구독으로 자동 갱신) ───

export function useChatRooms() {
  const queryClient = useQueryClient();
  const supabase = createClient();
  const { user } = useAuthStore();

  const query = useQuery({
    queryKey: ['chatRooms'],
    queryFn: () => api.get<SuccessResponse<ChatRoom[]>>('/chat/rooms'),
    enabled: !!user,
    retry: 2,
    retryDelay: 1000,
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

  // 대체 거래처 제안 메시지 별도 추출 — 채팅 페이지에서 배너로 표시
  const alternativePartnersSuggestion =
    lastMessage?.type === 'alternative_partners_suggestion' ? lastMessage : null;

  // 본인 user_id — negotiation_draft_detected 가드용
  const { user } = useAuthStore();

  // WebSocket으로 수신한 메시지를 React Query 캐시에 즉시 반영
  // message 타입과 system 타입 모두 캐시에 추가
  useEffect(() => {
    if (!lastMessage || !roomId) return;

    // ─ negotiation_draft_detected (US-2) ─────────────────────────────
    // 발신자 본인에게만 도착하는 이벤트. 해당 message_id 의 metadata.draft_negotiation
    // 를 캐시에 채워 MessageBubble 이 NegotiationDraftCard 를 렌더하도록 한다.
    // 메시지 자체 INSERT 는 별도 'message' 이벤트로 도착하므로 도착 순서 무관하게
    // 둘 다 처리할 수 있도록 캐시에 메시지가 아직 없으면 무시 (다음 message 도착 후
    // 이 분기는 다시 트리거되지 않으므로 fallback 으로 messages 캐시 invalidate).
    if (lastMessage.type === 'negotiation_draft_detected') {
      const draft = lastMessage.draft;
      const messageId = lastMessage.message_id;
      const targetUserId = lastMessage.target_user_id;
      // 본인에게 온 이벤트만 처리 (백엔드도 막지만 프론트도 가드)
      if (
        !draft ||
        !messageId ||
        !targetUserId ||
        !user?.id ||
        targetUserId !== user.id
      ) {
        return;
      }
      queryClient.setQueryData(
        ['messages', roomId],
        (old: SuccessResponse<Message[]> | undefined) => {
          if (!old) return old;
          let touched = false;
          const next = old.data.map((m) => {
            if (m.id !== messageId) return m;
            touched = true;
            return {
              ...m,
              metadata: { ...(m.metadata ?? {}), draft_negotiation: draft },
            };
          });
          // 메시지가 아직 캐시에 없으면 fallback 으로 refetch
          if (!touched) {
            queryClient.invalidateQueries({ queryKey: ['messages', roomId] });
            return old;
          }
          return { ...old, data: next };
        }
      );
      return;
    }

    if (lastMessage.type !== 'message' && lastMessage.type !== 'system') return;
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
      deleted_at: lastMessage.deleted_at ?? null,
      message_type: lastMessage.message_type ?? 'TEXT',
      metadata: lastMessage.metadata ?? null,
    };

    // 새 COUNTER_OFFER / DELIVERY_DATE_CHANGE 메시지가 도착하면 같은 order_id 의
    // 이전 PENDING 카드를 미리 SUPERSEDED 로 낙관적 갱신 — 그래야 invalidate 의
    // 네트워크 refetch 가 돌아오기 전에도 본인이 방금 새로 제시한 카드 위쪽의
    // 이전 PENDING 카드에 수락/거절 버튼이 남지 않는다 (issue.md #1 새로고침 전
    // stale 버튼 노출 버그).
    const incomingType = incomingMessage.message_type;
    const incomingMeta = incomingMessage.metadata;
    const incomingOrderId = incomingMeta?.order_id;
    const incomingStatus = incomingMeta?.status;
    const supersedesPrevious =
      !!incomingOrderId &&
      incomingStatus === 'PENDING' &&
      (incomingType === 'COUNTER_OFFER' || incomingType === 'DELIVERY_DATE_CHANGE');

    queryClient.setQueryData(
      ['messages', roomId],
      (old: SuccessResponse<Message[]> | undefined) => {
        if (!old) return { data: [incomingMessage] };
        const exists = old.data.some((m) => m.id === incomingMessage.id);
        // 이전 메시지 SUPERSEDED 낙관적 마킹 — 같은 order_id + 같은 카드 종류 + PENDING 인 것만
        const transformed = supersedesPrevious
          ? old.data.map((m) => {
              if (m.id === incomingMessage.id) return m;
              if (m.message_type !== incomingType) return m;
              const mMeta = m.metadata;
              if (!mMeta || mMeta.order_id !== incomingOrderId) return m;
              if (mMeta.status !== 'PENDING') return m;
              return {
                ...m,
                metadata: { ...mMeta, status: 'SUPERSEDED' as const },
              };
            })
          : old.data;
        if (exists) return { ...old, data: transformed };
        return { ...old, data: [...transformed, incomingMessage] };
      }
    );

    // 채팅방 목록의 last_message도 갱신
    queryClient.invalidateQueries({ queryKey: ['chatRooms'] });

    // 주문/협상 관련 이벤트 메시지면 주문/협상 캐시도 invalidate
    // (다른 탭에서 같은 사용자가 주문 페이지를 열어둔 경우 자동 동기화)
    const msgType = incomingMessage.message_type;
    if (msgType && ORDER_RELATED_TYPES.includes(msgType)) {
      const meta = incomingMessage.metadata;
      const orderId = meta?.order_id;
      queryClient.invalidateQueries({ queryKey: ['orders'] });
      if (orderId) {
        queryClient.invalidateQueries({ queryKey: ['order', orderId] });
        queryClient.invalidateQueries({ queryKey: ['negotiation', orderId] });
      }
      // 메시지 목록도 강제 refetch — 백엔드가 같은 offer_id 의 이전 messages.metadata.status 를
      // ACCEPTED/REJECTED/SUPERSEDED 로 동기화하므로 클라이언트가 stale 데이터를 가지고 있으면
      // 이전 카드의 수락/거절 버튼이 사라지지 않는다. WS 는 새 메시지 INSERT 만 푸시하고
      // 기존 메시지의 metadata UPDATE 는 알리지 않으므로 여기서 강제 invalidate.
      // 위의 setQueryData 로 이미 낙관적으로 마킹됐지만, 백엔드의 정식 status 값으로
      // 최종 동기화하기 위해 refetch 도 함께 트리거.
      queryClient.invalidateQueries({ queryKey: ['messages', roomId] });

      // 납품일 변경 이벤트 — delivery-date-changes 목록 + (수락 시) 캘린더 동기화
      if (
        msgType === 'DELIVERY_DATE_CHANGE' ||
        msgType === 'DELIVERY_DATE_ACCEPTED' ||
        msgType === 'DELIVERY_DATE_REJECTED'
      ) {
        if (orderId) {
          queryClient.invalidateQueries({
            queryKey: ['orders', orderId, 'delivery-date-changes'],
          });
        }
        if (msgType === 'DELIVERY_DATE_ACCEPTED') {
          // 수락 시 orders.delivery_date 업데이트 → 캘린더 이벤트 동기화
          queryClient.invalidateQueries({ queryKey: ['calendar'] });
        }
      }
    }
  }, [lastMessage, roomId, queryClient, user?.id]);

  return {
    messageQuery,
    isConnected,
    sendMessage: wsSendMessage,
    wsError,
    alternativePartnersSuggestion,
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

// ─── AI 답장 초안 생성 ───
// 백엔드 POST /chat/draft — 본인 채팅방 검증·컨텍스트 자동 주입.
// 사용자는 채팅 입력창에 `/초안 [지시]` 형태로 입력 → 메시지 전송이 아닌
// 이 mutation 으로 분기됨. 응답의 draft 텍스트는 미리보기 박스로 표시 후
// 사용자가 "사용" 버튼을 누르면 입력창에 채워진다 (자동 발송 안 함).

export function useGenerateChatDraft() {
  return useMutation({
    mutationFn: async ({
      roomId,
      instruction,
    }: {
      roomId: string;
      instruction: string;
    }) => {
      const res = await api.post<SuccessResponse<{ draft: string }>>(
        '/chat/draft',
        { room_id: roomId, instruction }
      );
      return res.data?.draft ?? '';
    },
  });
}

// ─── 채팅방에서 협상가 제시 ───
// 백엔드 POST /chat/rooms/{room_id}/counter-offer 호출.
// chat_room.order_id 가 없으면 백엔드가 400 으로 거부 → 호출 측에서 가드 필요.
// 응답: { data: CounterOffer } — 백엔드 order_service 가 자동으로 메시지 broadcast.
// onSuccess 시 messages / orders / order(id) / negotiation(id) 캐시를 모두 invalidate.

export function useSubmitCounterOfferViaChat(roomId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CounterOfferCreate) => {
      if (!roomId) {
        throw new Error('채팅방이 선택되지 않아 협상가를 제시할 수 없습니다.');
      }
      return api.post<SuccessResponse<CounterOffer>>(
        `/chat/rooms/${roomId}/counter-offer`,
        payload
      );
    },
    onSuccess: (res) => {
      const orderId = res.data.order_id;
      queryClient.invalidateQueries({ queryKey: ['orders'] });
      if (orderId) {
        queryClient.invalidateQueries({ queryKey: ['order', orderId] });
        queryClient.invalidateQueries({ queryKey: ['negotiation', orderId] });
      }
      // 백엔드가 같은 offer_id 의 이전 messages.metadata.status 를 SUPERSEDED 로 동기화 →
      // 이전 카드의 수락/거절 버튼이 자동 사라지도록 messages 캐시 refetch 필요.
      // 현재 roomId 뿐 아니라 다른 채팅방을 열어둔 탭도 함께 동기화하도록 broad 하게 invalidate.
      queryClient.invalidateQueries({ queryKey: ['messages'] });
      queryClient.invalidateQueries({ queryKey: ['chatRooms'] });
    },
  });
}

// ─── 협상 의도 감지 카드 [무시] (US-2) ─────────────────────────────
// PATCH /chat/messages/{message_id}/dismiss-draft-negotiation
// 발신자 본인만 호출 가능. 응답으로 dismissed_at 채워진 NegotiationDraft 받음.
// onSuccess 시 messages 캐시의 해당 메시지 metadata 만 낙관적 업데이트
// (전체 invalidate 안 함 — 다른 메시지 흔들림 방지).

interface DismissDraftResponse {
  message_id: string;
  draft_negotiation: NegotiationDraft;
}

export function useDismissNegotiationDraft(roomId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (messageId: string) =>
      api.patch<SuccessResponse<DismissDraftResponse>>(
        `/chat/messages/${messageId}/dismiss-draft-negotiation`
      ),
    onSuccess: (res, messageId) => {
      const updatedDraft = res.data.draft_negotiation;
      if (!roomId) return;
      queryClient.setQueryData(
        ['messages', roomId],
        (old: SuccessResponse<Message[]> | undefined) => {
          if (!old) return old;
          const next = old.data.map((m) => {
            if (m.id !== messageId) return m;
            return {
              ...m,
              metadata: {
                ...(m.metadata ?? {}),
                draft_negotiation: updatedDraft,
              },
            };
          });
          return { ...old, data: next };
        }
      );
    },
  });
}
