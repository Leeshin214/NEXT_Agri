'use client';

import { useState, useEffect } from 'react';
import { Bot, Send, Sparkles, ChevronLeft, ChevronRight } from 'lucide-react';
import { useAIStream } from '@/hooks/useAIStream';
import { useAuthStore } from '@/store/authStore';
import { useUIStore } from '@/store/uiStore';
import { sellerQuickPrompts, buyerQuickPrompts } from '@/constants/aiPrompts';

export default function AIChatPanel() {
  const [input, setInput] = useState('');
  const [isMobile, setIsMobile] = useState(false);
  const { response, isStreaming, stream } = useAIStream();
  const { user } = useAuthStore();
  const { aiPanelOpen, toggleAIPanel, setAIPanelOpen } = useUIStore();

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

  const handleSubmit = (text: string) => {
    if (!text.trim()) return;
    setInput('');
    stream(text);
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
              onClick={() => stream(qp.prompt, qp.type)}
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
      <div className="flex-1 overflow-y-auto p-4">
        {response ? (
          <div className="prose prose-sm max-w-none whitespace-pre-wrap text-sm text-gray-800 leading-relaxed">
            {response}
            {isStreaming && (
              <span className="inline-block h-4 w-0.5 animate-pulse bg-primary-600 ml-0.5 align-text-bottom" />
            )}
          </div>
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
            <Bot className="h-10 w-10 text-gray-200" />
            <p className="text-xs text-gray-400">
              질문을 입력하거나 빠른 프롬프트를 선택하세요
            </p>
          </div>
        )}
      </div>

      {/* 입력창 */}
      <div className="border-t border-gray-200 p-3 flex-shrink-0">
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
