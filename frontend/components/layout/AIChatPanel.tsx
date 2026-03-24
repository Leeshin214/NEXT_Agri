'use client';

import { useState } from 'react';
import { Bot, Send, Sparkles } from 'lucide-react';
import { useAIStream } from '@/hooks/useAIStream';
import { useAuthStore } from '@/store/authStore';
import { sellerQuickPrompts, buyerQuickPrompts } from '@/constants/aiPrompts';

export default function AIChatPanel() {
  const [input, setInput] = useState('');
  const { response, isStreaming, stream } = useAIStream();
  const { user } = useAuthStore();

  const quickPrompts = user?.role === 'SELLER' ? sellerQuickPrompts : buyerQuickPrompts;

  const handleSubmit = (text: string) => {
    if (!text.trim()) return;
    setInput('');
    stream(text);
  };

  return (
    <div className="flex w-1/2 flex-col border-l border-gray-200 bg-white">
      {/* 헤더 */}
      <div className="flex items-center gap-2 border-b border-gray-200 px-4 py-3">
        <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary-100">
          <Bot className="h-4 w-4 text-primary-600" />
        </div>
        <span className="text-sm font-semibold text-gray-800">AI 업무 도우미</span>
        {isStreaming && (
          <span className="ml-auto text-xs text-primary-500 animate-pulse">응답 중...</span>
        )}
      </div>

      {/* 빠른 프롬프트 */}
      <div className="border-b border-gray-100 px-3 py-2">
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

      {/* AI 응답 영역 */}
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
      <div className="border-t border-gray-200 p-3">
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
    </div>
  );
}
