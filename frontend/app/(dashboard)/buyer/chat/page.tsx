'use client';

import { useState, useRef, useEffect } from 'react';
import { Send, Sparkles, ArrowLeft } from 'lucide-react';
import PageHeader from '@/components/common/PageHeader';
import Modal from '@/components/common/Modal';
import { useChatRooms, useMessagesWithWebSocket, useMarkAsRead, useSummarizeChat } from '@/hooks/useChat';
import { useAuthStore } from '@/store/authStore';
import { cn } from '@/lib/utils';

export default function BuyerChatPage() {
  const { user } = useAuthStore();
  const [selectedRoomId, setSelectedRoomId] = useState<string | null>(null);
  const [message, setMessage] = useState('');
  const [showSummary, setShowSummary] = useState(false);
  const [summary, setSummary] = useState('');
  // 모바일에서 채팅방 선택 시 메시지 뷰로 전환하는 상태
  const [mobileView, setMobileView] = useState<'list' | 'messages'>('list');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const { data: roomsData, isLoading: roomsLoading, error: roomsError, refetch: refetchRooms } = useChatRooms();
  const { messageQuery, isConnected, sendMessage: wsSendMessage, wsError } =
    useMessagesWithWebSocket(selectedRoomId);
  const markAsRead = useMarkAsRead();
  const summarize = useSummarizeChat();

  const rooms = roomsData?.data ?? [];
  const messages = messageQuery.data?.data ?? [];

  const selectedRoom = rooms.find((r) => r.id === selectedRoomId);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    if (selectedRoomId) markAsRead.mutate(selectedRoomId);
  }, [selectedRoomId]); // eslint-disable-line react-hooks/exhaustive-deps

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

              {/* 메시지 목록 */}
              <div className="flex-1 overflow-y-auto p-4 space-y-3">
                {messages.map((msg) => {
                  const isMine = msg.sender_id === user?.id;
                  return (
                    <div
                      key={msg.id}
                      className={cn('flex', isMine ? 'justify-end' : 'justify-start')}
                    >
                      <div
                        className={cn(
                          'max-w-[75%] rounded-2xl px-4 py-2 text-sm',
                          isMine
                            ? 'bg-primary-600 text-white'
                            : 'bg-gray-100 text-gray-900'
                        )}
                      >
                        {msg.content}
                      </div>
                    </div>
                  );
                })}
                <div ref={messagesEndRef} />
              </div>

              {/* 입력창 */}
              <div className="border-t border-gray-200 p-4">
                <div className="flex gap-2">
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
