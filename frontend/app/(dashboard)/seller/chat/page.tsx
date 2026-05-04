'use client';

import { useState, useRef, useEffect } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import { Sparkles, ArrowLeft, AlertTriangle, X } from 'lucide-react';
import PageHeader from '@/components/common/PageHeader';
import Modal from '@/components/common/Modal';
import MessageBubble from '@/components/chat/MessageBubble';
import OrderContextBanner from '@/components/chat/OrderContextBanner';
import PriceOfferPopover from '@/components/chat/PriceOfferPopover';
import DeliveryDatePopover from '@/components/chat/DeliveryDatePopover';
import ChatHeaderStatusControl from '@/components/chat/ChatHeaderStatusControl';
import ChatRoomList from '@/components/chat/ChatRoomList';
import MessageInput from '@/components/chat/MessageInput';
import {
  useChatRooms,
  useMessagesWithWebSocket,
  useMarkAsRead,
  useSummarizeChat,
  useCreateChatRoom,
  useDismissNegotiationDraft,
} from '@/hooks/useChat';
import { useOrder } from '@/hooks/useOrders';
import { useAuthStore } from '@/store/authStore';
import { cn } from '@/lib/utils';
import { isSystemMessageContent } from '@/constants/chat';
import type { AlternativePartner, NegotiationDraft } from '@/types';
import type { PriceOfferPrefill } from '@/components/chat/PriceOfferPopover';

export default function SellerChatPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  // isHydrated 까지 함께 구독해야 첫 렌더에서 user.id 가 undefined 인 채로
  // MessageBubble 이 그려지는 race 를 막을 수 있다 (첫 메시지 좌측 정렬 버그).
  const { user, isHydrated } = useAuthStore();
  const [selectedRoomId, setSelectedRoomId] = useState<string | null>(null);
  const [showSummary, setShowSummary] = useState(false);
  const [summary, setSummary] = useState('');
  // 모바일에서 채팅방 선택 시 메시지 뷰로 전환하는 상태
  const [mobileView, setMobileView] = useState<'list' | 'messages'>('list');
  // 대체 거래처 제안 배너 닫기 상태 (다음 suggestion 도착 시 자동 초기화)
  const [suggestionDismissed, setSuggestionDismissed] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // 주문 상세 → 채팅 이동 시 room_id 쿼리스트링으로 자동 선택
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
  // US-2 협상 의도 감지 — [무시] PATCH + [등록] 시 PriceOfferPopover prefill
  const dismissDraft = useDismissNegotiationDraft(selectedRoomId);
  const [draftPrefill, setDraftPrefill] = useState<PriceOfferPrefill | null>(null);

  const rooms = roomsData?.data ?? [];
  const messages = messageQuery.data?.data ?? [];

  const selectedRoom = rooms.find((r) => r.id === selectedRoomId);
  const linkedOrderId = selectedRoom?.order_id ?? null;
  // 헤더 배너에서 사용할 주문 정보를 빠른 액션 popover 들의 placeholder/가드로 재사용
  const { data: linkedOrderData } = useOrder(linkedOrderId ?? '');
  const linkedOrderTotal = linkedOrderData?.data?.total_amount ?? null;
  const linkedOrderStatus = linkedOrderData?.data?.status ?? null;
  const linkedOrderDeliveryDate = linkedOrderData?.data?.delivery_date ?? null;

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

  const handleSend = (content: string) => {
    if (!selectedRoomId) return;
    wsSendMessage(content);
  };

  // US-2 — 협상 감지 카드 [등록]: PriceOfferPopover 를 prefill 한 채로 연다.
  // total = quantity * unit_price 로 계산해서 amount 에 prefill (둘 다 있을 때만).
  // notes 에는 감지된 자연어 요약을 채워 사용자가 그대로 제출하거나 수정 가능.
  const handleAcceptDraft = (draft: NegotiationDraft) => {
    const total =
      typeof draft.quantity === 'number' &&
      typeof draft.unit_price === 'number' &&
      draft.quantity > 0 &&
      draft.unit_price > 0
        ? draft.quantity * draft.unit_price
        : undefined;
    const noteParts: string[] = [];
    if (draft.product_name) noteParts.push(draft.product_name);
    if (typeof draft.quantity === 'number' && draft.quantity > 0) {
      noteParts.push(`${draft.quantity}${draft.unit ?? ''}`);
    }
    if (typeof draft.unit_price === 'number' && draft.unit_price > 0) {
      noteParts.push(`단가 ${draft.unit_price.toLocaleString('ko-KR')}원`);
    }
    setDraftPrefill({
      amount: total,
      notes: noteParts.length > 0 ? noteParts.join(' / ') : undefined,
    });
  };

  const handleDismissDraft = (messageId: string) => {
    dismissDraft.mutate(messageId);
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
      router.push(`/seller/chat?room_id=${newRoomId}`);
      // 같은 페이지 내 라우팅이므로 selectedRoomId도 직접 갱신
      setSelectedRoomId(newRoomId);
      setMobileView('messages');
    } catch (e) {
      console.error('[seller/chat] 대체 거래처 채팅방 생성 실패:', e);
    }
  };

  // 미리보기에 노출할 알림 — 닫혔거나 제안 없으면 null
  const visibleSuggestion =
    !suggestionDismissed && alternativePartnersSuggestion ? alternativePartnersSuggestion : null;
  const previewAlternatives = (visibleSuggestion?.alternatives ?? []).slice(0, 3);

  // hydration 미완료 또는 user 없는 상태에서는 메시지 본인/상대 판별이 불가능 →
  // 잘못된 정렬로 첫 진입 직후 첫 메시지가 좌측 정렬되는 버그를 막기 위해 가드.
  // AuthGuard 가 이미 user 를 채워주지만 store 구독 타이밍 차로 1프레임 비어 보일 수
  // 있으므로 페이지 레벨에서도 한 번 더 확인한다.
  if (!isHydrated || !user?.id) {
    return (
      <div>
        <PageHeader title="채팅" description="바이어와 실시간으로 대화하세요" />
        <div className="flex h-[calc(100vh-200px)] items-center justify-center rounded-xl bg-white text-sm text-gray-500 shadow-sm">
          채팅을 불러오는 중...
        </div>
      </div>
    );
  }

  return (
    <div>
      <PageHeader title="채팅" description="바이어와 실시간으로 대화하세요" />

      <div className="flex h-[calc(100vh-200px)] rounded-xl bg-white shadow-sm overflow-hidden">
        {/* 채팅방 목록 — 거래처별 그룹핑 (모바일: mobileView==='list'일 때만 표시, md 이상: 항상 표시) */}
        <div
          className={cn(
            'border-r border-gray-200',
            // 모바일: 전체 너비, mobileView에 따라 표시/숨김
            'w-full md:w-72 md:flex-shrink-0',
            mobileView === 'list' ? 'flex flex-col' : 'hidden md:flex md:flex-col'
          )}
        >
          <ChatRoomList
            rooms={rooms}
            myRole="SELLER"
            selectedRoomId={selectedRoomId}
            onSelectRoom={handleRoomSelect}
            isLoading={roomsLoading}
            error={roomsError}
            onRetry={refetchRooms}
          />
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
                <div className="flex items-center gap-2">
                  {/* 주문 상태 배지 + 다음 상태 변경 드롭다운 — 연결된 주문이 있을 때만 표시 */}
                  <ChatHeaderStatusControl
                    orderId={linkedOrderId}
                    currentStatus={linkedOrderStatus}
                    role="seller"
                  />
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
              </div>

              {/* 주문 컨텍스트 배너 — 채팅방에 연결된 주문이 있을 때만 표시 */}
              {linkedOrderId && (
                <OrderContextBanner
                  orderId={linkedOrderId}
                  role="seller"
                  onOpenOrder={(id) =>
                    router.push(`/seller/orders?id=${id}`)
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
                        currentUserId={user?.id}
                      />
                    );
                  }
                  return (
                    <MessageBubble
                      key={msg.id}
                      message={msg}
                      currentUserId={user?.id}
                      onAcceptNegotiationDraft={handleAcceptDraft}
                      onDismissNegotiationDraft={handleDismissDraft}
                      isDismissingNegotiationDraft={dismissDraft.isPending}
                    />
                  );
                })}
                <div ref={messagesEndRef} />
              </div>

              {/* 입력창 — `/초안 [지시]` 슬래시 명령으로 AI 답장 초안 생성 가능 */}
              <MessageInput
                roomId={selectedRoomId}
                isConnected={isConnected}
                onSend={handleSend}
                leadingActions={
                  <>
                    <PriceOfferPopover
                      roomId={selectedRoomId}
                      orderId={linkedOrderId}
                      currentTotal={linkedOrderTotal}
                      prefill={draftPrefill}
                      onPrefillConsumed={() => setDraftPrefill(null)}
                    />
                    <DeliveryDatePopover
                      roomId={selectedRoomId}
                      orderId={linkedOrderId}
                      orderStatus={linkedOrderStatus}
                      currentDeliveryDate={linkedOrderDeliveryDate}
                    />
                  </>
                }
              />
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
