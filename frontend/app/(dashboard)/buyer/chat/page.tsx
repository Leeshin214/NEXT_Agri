'use client';

import { useState, useRef, useEffect } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import { Send, Sparkles, ArrowLeft, AlertTriangle, X } from 'lucide-react';
import PageHeader from '@/components/common/PageHeader';
import Modal from '@/components/common/Modal';
import MessageBubble from '@/components/chat/MessageBubble';
import OrderContextBanner from '@/components/chat/OrderContextBanner';
import PriceOfferPopover from '@/components/chat/PriceOfferPopover';
import {
  useChatRooms,
  useMessagesWithWebSocket,
  useMarkAsRead,
  useSummarizeChat,
  useCreateChatRoom,
} from '@/hooks/useChat';
import { useOrder } from '@/hooks/useOrders';
import { useAuthStore } from '@/store/authStore';
import { cn } from '@/lib/utils';
import { isSystemMessageContent } from '@/constants/chat';
import type { AlternativePartner } from '@/types';

export default function BuyerChatPage() {
  const router = useRouter();
  const { user } = useAuthStore();
  const searchParams = useSearchParams();
  const [selectedRoomId, setSelectedRoomId] = useState<string | null>(null);
  const [message, setMessage] = useState('');
  const [showSummary, setShowSummary] = useState(false);
  const [summary, setSummary] = useState('');
  // 모바일에서 채팅방 선택 시 메시지 뷰로 전환하는 상태
  const [mobileView, setMobileView] = useState<'list' | 'messages'>('list');
  // 대체 거래처 제안 배너 닫기 상태 (다음 suggestion 도착 시 자동 초기화)
  const [suggestionDismissed, setSuggestionDismissed] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // browse 페이지 견적 요청 후 room_id 쿼리스트링으로 자동 선택
  useEffect(() => {
    const roomIdParam = searchParams.get('room_id');
    if (roomIdParam) {
      setSelectedRoomId(roomIdParam);
      setMobileView('messages');
    }
  }, [searchParams]);

  const { data: roomsData, isLoading: roomsLoading, error: roomsError, refetch: refetchRooms } = useChatRooms();
  const { messageQuery, isConnected, sendMessage: wsSendMessage, wsError, alternativePartnersSuggestion } =
    useMessagesWithWebSocket(selectedRoomId);
  const markAsRead = useMarkAsRead();
  const summarize = useSummarizeChat();
  const createChatRoom = useCreateChatRoom();

  const rooms = roomsData?.data ?? [];
  const messages = messageQuery.data?.data ?? [];

  const selectedRoom = rooms.find((r) => r.id === selectedRoomId);
  const linkedOrderId = selectedRoom?.order_id ?? null;
  // 헤더 배너에서 사용할 주문 합계를 가격 제시 popover 의 placeholder 로 재사용
  const { data: linkedOrderData } = useOrder(linkedOrderId ?? '');
  const linkedOrderTotal = linkedOrderData?.data?.total_amount ?? null;

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    if (selectedRoomId) markAsRead.mutate(selectedRoomId);
  }, [selectedRoomId]); // eslint-disable-line react-hooks/exhaustive-deps

  // 새 suggestion이 도착하면 dismissed 상태 초기화
  useEffect(() => {
    if (alternativePartnersSuggestion) setSuggestionDismissed(false);
  }, [alternativePartnersSuggestion]);

  const handleRoomSelect = (roomId: string) => {
    setSelectedRoomId(roomId);
    setMobileView('messages');
  };

  const handleBackToList = () => {
    setMobileView('list');
  };

  const handleSend = () => {
    if (!message.trim() || !selectedRoomId) return;
    wsSendMessage(message);
    setMessage('');
  };

  const handleSummarize = async () => {
    if (messages.length === 0) return;
    const recentMessages = messages
      .slice(-20)
      .map((m) => `${m.sender_id === user?.id ? '나' : selectedRoom?.partner_name || '상대방'}: ${m.content}`)
      .join('\n');

    const result = await summarize.mutateAsync(recentMessages);
    setSummary(result.data.summary);
    setShowSummary(true);
  };

  // 대체 거래처 클릭 → 채팅방 개설 후 해당 방으로 이동
  const handleAlternativeClick = async (partner: AlternativePartner) => {
    if (!partner.user_id || createChatRoom.isPending) return;
    try {
      const res = await createChatRoom.mutateAsync({ partner_user_id: partner.user_id });
      const newRoomId = res.data.id;
      setSuggestionDismissed(true);
      router.push(`/buyer/chat?room_id=${newRoomId}`);
      // 같은 페이지 내 라우팅이므로 selectedRoomId도 직접 갱신
      setSelectedRoomId(newRoomId);
      setMobileView('messages');
    } catch (e) {
      console.error('[buyer/chat] 대체 거래처 채팅방 생성 실패:', e);
    }
  };

  // 미리보기에 노출할 알림 — 닫혔거나 제안 없으면 null
  const visibleSuggestion =
    !suggestionDismissed && alternativePartnersSuggestion ? alternativePartnersSuggestion : null;
  const previewAlternatives = (visibleSuggestion?.alternatives ?? []).slice(0, 3);

  return (
    <div>
      <PageHeader title="채팅" description="공급처와 실시간으로 대화하세요" />

      <div className="flex h-[calc(100vh-200px)] rounded-xl bg-white shadow-sm overflow-hidden">
        {/* 채팅방 목록 — 모바일: mobileView==='list'일 때만 표시, md 이상: 항상 표시 */}
        <div
          className={cn(
            'border-r border-gray-200 overflow-y-auto',
            'w-full md:w-72 md:flex-shrink-0',
            mobileView === 'list' ? 'flex flex-col' : 'hidden md:flex md:flex-col'
          )}
        >
          {roomsLoading ? (
            <div className="flex items-center justify-center p-8">
              <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary-600 border-t-transparent" />
            </div>
          ) : roomsError ? (
            <div className="p-4 text-sm text-red-500">
              채팅방을 불러오지 못했습니다.
              <button onClick={() => refetchRooms()} className="ml-2 text-primary-600 underline">
                다시 시도
              </button>
            </div>
          ) : rooms.length === 0 ? (
            <p className="p-4 text-sm text-gray-400">채팅방이 없습니다.</p>
          ) : (
            rooms.map((room) => (
              <button
                key={room.id}
                onClick={() => handleRoomSelect(room.id)}
                className={cn(
                  'w-full border-b border-gray-100 p-4 text-left hover:bg-gray-50',
                  selectedRoomId === room.id && 'bg-primary-50'
                )}
              >
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium text-gray-900">
                    {room.partner_name || '상대방'}
                  </p>
                  {room.unread_count > 0 && (
                    <span className="flex h-5 min-w-[20px] items-center justify-center rounded-full bg-primary-600 px-1.5 text-[10px] font-bold text-white">
                      {room.unread_count}
                    </span>
                  )}
                </div>
                <p className="text-xs text-gray-500">{room.partner_company}</p>
                {room.last_message && (
                  <p className="mt-1 truncate text-xs text-gray-400">
                    {room.last_message}
                  </p>
                )}
              </button>
            ))
          )}
        </div>

        {/* 메시지 영역 — 모바일: mobileView==='messages'일 때만 표시, md 이상: 항상 표시 */}
        <div
          className={cn(
            'flex flex-1 flex-col',
            mobileView === 'messages' ? 'flex' : 'hidden md:flex'
          )}
        >
          {!selectedRoomId ? (
            <div className="flex flex-1 items-center justify-center text-sm text-gray-400">
              채팅방을 선택하세요
            </div>
          ) : (
            <>
              {/* 채팅방 헤더 */}
              <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3">
                <div className="flex items-center gap-2">
                  {/* 모바일 뒤로가기 버튼 */}
                  <button
                    onClick={handleBackToList}
                    className="flex h-8 w-8 items-center justify-center rounded-lg text-gray-400 hover:bg-gray-100 md:hidden"
                    aria-label="목록으로"
                  >
                    <ArrowLeft className="h-4 w-4" />
                  </button>
                  <div>
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-semibold text-gray-900">
                        {selectedRoom?.partner_name || '상대방'}
                      </p>
                      <span
                        className={cn(
                          'h-2 w-2 rounded-full',
                          isConnected ? 'bg-green-500' : 'bg-gray-300'
                        )}
                        title={isConnected ? '연결됨' : '연결 중...'}
                      />
                    </div>
                    <p className="text-xs text-gray-500">{selectedRoom?.partner_company}</p>
                    {wsError && (
                      <p className="mt-0.5 text-xs text-red-500">{wsError}</p>
                    )}
                  </div>
                </div>
                <button
                  onClick={handleSummarize}
                  disabled={summarize.isPending || messages.length === 0}
                  className="flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-50"
                >
                  <Sparkles className="h-3.5 w-3.5 text-purple-500" />
                  <span className="hidden sm:inline">{summarize.isPending ? 'AI 요약 중...' : 'AI 요약'}</span>
                  <span className="sm:hidden">요약</span>
                </button>
              </div>

              {/* 주문 컨텍스트 배너 — 채팅방에 연결된 주문이 있을 때만 표시 */}
              {linkedOrderId && (
                <OrderContextBanner
                  orderId={linkedOrderId}
                  role="buyer"
                  onOpenOrder={(id) =>
                    router.push(`/buyer/orders?id=${id}`)
                  }
                />
              )}

              {/* 대체 거래처 제안 배너 */}
              {visibleSuggestion && (
                <div className="border-b border-yellow-200 bg-yellow-50 px-4 py-3">
                  <div className="flex items-start gap-2">
                    <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0 text-yellow-500" aria-hidden="true" />
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-medium text-yellow-900">
                        {visibleSuggestion.message ?? '대체 거래처가 제안됐습니다.'}
                        {visibleSuggestion.category && (
                          <span className="ml-1 text-yellow-700">({visibleSuggestion.category})</span>
                        )}
                      </p>
                      {previewAlternatives.length > 0 ? (
                        <ul className="mt-2 space-y-1.5">
                          {previewAlternatives.map((p) => (
                            <li key={p.user_id}>
                              <button
                                onClick={() => handleAlternativeClick(p)}
                                disabled={createChatRoom.isPending}
                                className="flex w-full items-center justify-between gap-2 rounded-md border border-yellow-200 bg-white px-3 py-2 text-left text-xs hover:border-yellow-400 hover:bg-yellow-50 disabled:opacity-50"
                              >
                                <div className="min-w-0 flex-1">
                                  <p className="truncate text-sm font-medium text-gray-900">
                                    {p.name}
                                    {p.company_name && (
                                      <span className="ml-1 text-xs text-gray-500">({p.company_name})</span>
                                    )}
                                  </p>
                                  <p className="mt-0.5 truncate text-[11px] text-gray-500">
                                    {typeof p.trade_count === 'number' && (
                                      <span>거래 {p.trade_count}회</span>
                                    )}
                                    {typeof p.stock_quantity === 'number' && p.stock_quantity > 0 && (
                                      <span className="ml-2">
                                        재고 {p.stock_quantity.toLocaleString()}
                                        {p.unit ? p.unit : ''}
                                      </span>
                                    )}
                                    {typeof p.price_per_unit === 'number' && p.price_per_unit > 0 && (
                                      <span className="ml-2">
                                        {p.price_per_unit.toLocaleString()}원
                                        {p.unit ? `/${p.unit}` : ''}
                                      </span>
                                    )}
                                  </p>
                                </div>
                                <span className="flex-shrink-0 text-xs font-medium text-primary-600">
                                  채팅 시작
                                </span>
                              </button>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="mt-1 text-[11px] text-yellow-700">
                          현재 추천 가능한 대체 거래처가 없습니다.
                        </p>
                      )}
                    </div>
                    <button
                      onClick={() => setSuggestionDismissed(true)}
                      className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-md text-yellow-700 hover:bg-yellow-100"
                      aria-label="알림 닫기"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              )}

              {/* 메시지 목록 — message_type 별 분기는 MessageBubble 내부에서 처리 */}
              <div className="flex-1 overflow-y-auto p-4 space-y-3">
                {messages.map((msg) => {
                  // 레거시 호환 — message_type 이 없고 prefix 기반 시스템 메시지면 SYSTEM 으로 변환
                  if (!msg.message_type && isSystemMessageContent(msg.content)) {
                    return (
                      <MessageBubble
                        key={msg.id}
                        message={{ ...msg, message_type: 'SYSTEM' }}
                      />
                    );
                  }
                  return <MessageBubble key={msg.id} message={msg} />;
                })}
                <div ref={messagesEndRef} />
              </div>

              {/* 입력창 */}
              <div className="border-t border-gray-200 p-4">
                <div className="flex gap-2">
                  <PriceOfferPopover
                    roomId={selectedRoomId}
                    orderId={linkedOrderId}
                    currentTotal={linkedOrderTotal}
                  />
                  <input
                    value={message}
                    onChange={(e) => setMessage(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.nativeEvent.isComposing) return;
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        handleSend();
                      }
                    }}
                    placeholder="메시지를 입력하세요..."
                    className="flex-1 rounded-lg border border-gray-300 px-4 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
                  />
                  <button
                    onClick={handleSend}
                    disabled={!message.trim() || !isConnected}
                    className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary-600 text-white hover:bg-primary-700 disabled:opacity-50"
                  >
                    <Send className="h-4 w-4" />
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* AI 요약 모달 */}
      <Modal isOpen={showSummary} onClose={() => setShowSummary(false)} title="AI 대화 요약" size="md">
        <div className="prose prose-sm max-w-none whitespace-pre-wrap text-gray-800">
          {summary}
        </div>
      </Modal>
    </div>
  );
}
