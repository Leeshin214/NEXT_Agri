'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { Bot, Send, Sparkles, ChevronLeft, ChevronRight, ChevronDown, AlertTriangle } from 'lucide-react';
import { useAIStream } from '@/hooks/useAIStream';
import { useAuthStore } from '@/store/authStore';
import { useUIStore } from '@/store/uiStore';
import { useAIChatStore } from '@/store/aiChatStore';
import { useAIHistory } from '@/hooks/useAIHistory';
import { sellerQuickPrompts, buyerQuickPrompts } from '@/constants/aiPrompts';

// 사용자가 의도적으로 위로 스크롤한 것으로 간주할 임계값(px).
// 이 값보다 멀면 자동 스크롤을 멈추고 "맨 밑으로" 버튼을 노출한다.
const BOTTOM_THRESHOLD_PX = 80;

export default function AIChatPanel() {
  const [input, setInput] = useState('');
  const [isMobile, setIsMobile] = useState(false);
  const { isStreaming, manualReview, stream } = useAIStream();
  const { user } = useAuthStore();
  const { aiPanelOpen, toggleAIPanel, setAIPanelOpen } = useUIStore();
  // 채팅 페이지에서 publish 한 현재 채팅방 컨텍스트 — stream 호출 시 백엔드에 함께 전달
  const aiChatContext = useUIStore((s) => s.aiChatContext);

  // AI 히스토리 hydrate 트리거 + store 의 turns 구독
  useAIHistory(100);
  const turns = useAIChatStore((s) => s.turns);
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const lastTurn = turns.length > 0 ? turns[turns.length - 1] : null;
  const showManualReviewBanner = manualReview && !!lastTurn && !lastTurn.pending;

  const quickPrompts = user?.role === 'SELLER' ? sellerQuickPrompts : buyerQuickPrompts;

  // xl 이상에서는 항상 열린 상태, 모바일 여부 감지
  useEffect(() => {
    const handleResize = () => {
      const width = window.innerWidth;
      setIsMobile(width < 768);
      if (width >= 1280) {
        setAIPanelOpen(true);
      }
    };
    handleResize();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [setAIPanelOpen]);

  // 메시지 컨테이너 스크롤 위치 추적 — 사용자가 위로 스크롤했는지 판별
  useEffect(() => {
    const el = messagesContainerRef.current;
    if (!el) return;
    const onScroll = () => {
      const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
      setIsAtBottom(distance < BOTTOM_THRESHOLD_PX);
    };
    // 초기 한 번 — 사이즈 계산 직후 정확한 상태로 진입
    onScroll();
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => el.removeEventListener('scroll', onScroll);
  }, [aiPanelOpen]);

  const scrollToBottom = useCallback((smooth = true) => {
    const el = messagesContainerRef.current;
    if (!el) return;
    el.scrollTo({
      top: el.scrollHeight,
      behavior: smooth ? 'smooth' : 'auto',
    });
  }, []);

  // 패널이 처음 열리거나 첫 turns 가 hydrate 되었을 때 즉시 맨 아래로
  // (페이지 전환 후 패널이 다시 보일 때 최신 메시지가 보이도록 보장)
  useEffect(() => {
    if (!aiPanelOpen) return;
    if (turns.length === 0) return;
    // 마운트 직후 레이아웃 확정 후 1프레임 뒤 즉시 점프
    const raf = requestAnimationFrame(() => scrollToBottom(false));
    return () => cancelAnimationFrame(raf);
    // turns.length 0→N 전환 시에도 동일하게 동작
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aiPanelOpen, turns.length === 0]);

  // 새 메시지 / 응답 갱신 시: 사용자가 바닥 근처에 있을 때만 자동 따라가기
  useEffect(() => {
    if (!isAtBottom) return;
    scrollToBottom(true);
  }, [turns.length, lastTurn?.response, isAtBottom, scrollToBottom]);

  const handleSubmit = (text: string) => {
    if (!text.trim()) return;
    setInput('');
    stream(text, undefined, aiChatContext.orderId, aiChatContext.roomId);
  };

  // 채팅 UI — 확장 상태에서 공통으로 사용
  const chatUI = (
    <>
      {/* 헤더 */}
      <div className="flex items-center gap-2 border-b border-gray-200 px-4 py-3 flex-shrink-0">
        <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary-100 flex-shrink-0">
          <Bot className="h-4 w-4 text-primary-600" />
        </div>
        <span className="flex-1 min-w-0 truncate text-sm font-semibold text-gray-800">
          AI 업무 도우미
        </span>
        {isStreaming && (
          <span className="flex-shrink-0 text-xs text-primary-500 animate-pulse">응답 중...</span>
        )}
        <button
          onClick={toggleAIPanel}
          className="ml-1 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-md hover:bg-gray-100 text-gray-400 hover:text-gray-600"
          aria-label="AI 패널 접기"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>

      {/* 빠른 프롬프트 */}
      <div className="border-b border-gray-100 px-3 py-2 flex-shrink-0">
        <div className="flex flex-wrap gap-1.5">
          {quickPrompts.map((qp) => (
            <button
              key={qp.type}
              onClick={() =>
                stream(qp.prompt, qp.type, aiChatContext.orderId, aiChatContext.roomId)
              }
              disabled={isStreaming}
              className="flex items-center gap-1 rounded-full border border-gray-200 bg-gray-50 px-2.5 py-1 text-xs text-gray-600 hover:border-primary-300 hover:bg-primary-50 hover:text-primary-700 disabled:opacity-50"
            >
              <Sparkles className="h-3 w-3 flex-shrink-0" />
              {qp.label}
            </button>
          ))}
        </div>
      </div>

      {/* 응답 영역 */}
      <div ref={messagesContainerRef} className="flex-1 overflow-y-auto p-3 space-y-1.5">
        {turns.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
            <Bot className="h-10 w-10 text-gray-200" />
            <p className="text-xs text-gray-400">
              질문을 입력하거나 빠른 프롬프트를 선택하세요
            </p>
          </div>
        ) : (
          <>
            {turns.map((turn, idx) => {
              const dateLabel = turn.created_at.slice(0, 10);
              const prevDateLabel = idx > 0 ? turns[idx - 1].created_at.slice(0, 10) : null;
              const showDivider = dateLabel !== prevDateLabel;
              const isLastPending = idx === turns.length - 1 && turn.pending && turn.response === '';

              return (
                <div key={turn.id}>
                  {showDivider && (
                    <div className="flex items-center gap-2 my-2">
                      <div className="flex-1 h-px bg-gray-200" />
                      <span className="text-[10px] text-gray-400 whitespace-nowrap">{dateLabel}</span>
                      <div className="flex-1 h-px bg-gray-200" />
                    </div>
                  )}
                  {/* 사용자 메시지 — 오른쪽 */}
                  <div className="flex justify-end mb-1">
                    <div className="max-w-[85%] rounded-2xl bg-primary-100 px-3 py-1.5 text-xs text-primary-900 break-words whitespace-pre-wrap">
                      {turn.prompt}
                    </div>
                  </div>
                  {/* manual review 배너 — 마지막 turn 응답 직후 */}
                  {idx === turns.length - 1 && showManualReviewBanner && (
                    <div className="bg-yellow-50 border border-yellow-400 rounded p-2 mb-1 flex items-start gap-1.5">
                      <AlertTriangle className="h-3.5 w-3.5 text-yellow-500 flex-shrink-0 mt-0.5" aria-hidden="true" />
                      <span className="text-yellow-800 text-[11px] leading-snug">
                        AI 답변 검토 필요 — 결과를 직접 확인해 주세요.
                      </span>
                    </div>
                  )}
                  {/* AI 응답 — 왼쪽 */}
                  <div className="flex justify-start mb-1">
                    <div className="max-w-[85%] rounded-2xl bg-gray-100 px-3 py-1.5 text-xs text-gray-800 break-words whitespace-pre-wrap leading-relaxed">
                      {isLastPending ? (
                        <span className="inline-block h-3 w-0.5 animate-pulse bg-primary-600" />
                      ) : (
                        <>
                          {turn.response}
                          {idx === turns.length - 1 && isStreaming && (
                            <span className="inline-block h-3 w-0.5 animate-pulse bg-primary-600 ml-0.5" />
                          )}
                        </>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </>
        )}
      </div>

      {/* 입력창 — 위에 "맨 밑으로 내리기" 버튼이 absolute 로 떠 있음 */}
      <div className="relative border-t border-gray-200 p-3 flex-shrink-0">
        {/* 맨 밑으로 내리기 버튼 — 바닥에서 멀어졌을 때만 노출 */}
        <button
          type="button"
          onClick={() => scrollToBottom(true)}
          aria-label="맨 아래로 이동"
          className={`absolute -top-8 left-1/2 -translate-x-1/2 z-10 flex h-9 w-9 items-center justify-center rounded-full border border-gray-200 bg-white text-gray-600 shadow-md hover:bg-gray-50 hover:text-primary-600 transition-opacity duration-200 ${
            isAtBottom || turns.length === 0
              ? 'pointer-events-none opacity-0'
              : 'opacity-100'
          }`}
        >
          <ChevronDown className="h-4 w-4" />
        </button>
        <div className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSubmit(input);
              }
            }}
            placeholder="AI에게 질문하세요..."
            disabled={isStreaming}
            className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 disabled:opacity-50"
          />
          <button
            onClick={() => handleSubmit(input)}
            disabled={!input.trim() || isStreaming}
            className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg bg-primary-600 text-white hover:bg-primary-700 disabled:opacity-50"
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
      </div>
    </>
  );

  // 축소 상태: 모든 화면에서 w-12 바 표시
  if (!aiPanelOpen) {
    return (
      <div className="flex w-12 flex-shrink-0 flex-col items-center border-l border-gray-200 bg-white py-4">
        <button
          onClick={toggleAIPanel}
          className="flex flex-col items-center gap-2 text-gray-400 hover:text-primary-600 transition-colors"
          aria-label="AI 패널 열기"
        >
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary-100">
            <Bot className="h-4 w-4 text-primary-600" />
          </div>
          <ChevronLeft className="h-4 w-4" />
        </button>
      </div>
    );
  }

  // 확장 상태 — 모바일: fixed 오버레이, md 이상: 인라인
  if (isMobile) {
    return (
      <>
        {/* 반투명 오버레이 배경 */}
        <div
          className="fixed inset-0 z-40 bg-black/40"
          onClick={toggleAIPanel}
          aria-hidden="true"
        />
        {/* 패널 본체 */}
        <div className="fixed inset-y-0 right-0 z-50 flex w-[320px] flex-col border-l border-gray-200 bg-white shadow-xl">
          {chatUI}
        </div>
      </>
    );
  }

  // 확장 상태 — md 이상: 인라인 flex
  return (
    <div className="flex w-[360px] xl:w-[400px] 2xl:w-[440px] flex-shrink-0 flex-col border-l border-gray-200 bg-white">
      {chatUI}
    </div>
  );
}
