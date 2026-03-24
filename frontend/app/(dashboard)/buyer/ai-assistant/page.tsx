'use client';

import { useState } from 'react';
import { Send, Sparkles } from 'lucide-react';
import PageHeader from '@/components/common/PageHeader';
import { useAIStream } from '@/hooks/useAIStream';
import { buyerQuickPrompts } from '@/constants/aiPrompts';

export default function BuyerAIAssistantPage() {
  const [input, setInput] = useState('');
  const { response, isStreaming, stream } = useAIStream();

  const handleSubmit = (text: string) => {
    if (!text.trim()) return;
    setInput('');
    stream(text);
  };

  return (
    <div>
      <PageHeader title="AI 업무 도우미" description="AI가 구매 업무를 도와드립니다" />

      {/* 빠른 프롬프트 */}
      <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {buyerQuickPrompts.map((qp) => (
          <button
            key={qp.type}
            onClick={() => stream(qp.prompt, qp.type)}
            disabled={isStreaming}
            className="flex items-center gap-2 rounded-xl border border-gray-200 bg-white p-4 text-left text-sm hover:border-primary-300 hover:bg-primary-50 disabled:opacity-50"
          >
            <Sparkles className="h-4 w-4 flex-shrink-0 text-primary-600" />
            <span className="text-gray-700">{qp.label}</span>
          </button>
        ))}
      </div>

      {/* AI 응답 영역 */}
      <div className="mb-4 min-h-[300px] rounded-xl bg-white p-6 shadow-sm">
        {response ? (
          <div className="prose prose-sm max-w-none whitespace-pre-wrap text-gray-800">
            {response}
            {isStreaming && (
              <span className="inline-block h-4 w-1 animate-pulse bg-primary-600 ml-0.5" />
            )}
          </div>
        ) : (
          <div className="flex h-[250px] items-center justify-center text-sm text-gray-400">
            질문을 입력하거나 빠른 프롬프트를 선택하세요
          </div>
        )}
      </div>

      {/* 입력창 */}
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
          placeholder="AI에게 질문하세요 (예: 이번 주 납품 일정 알려줘)"
          disabled={isStreaming}
          className="flex-1 rounded-lg border border-gray-300 px-4 py-3 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 disabled:opacity-50"
        />
        <button
          onClick={() => handleSubmit(input)}
          disabled={!input.trim() || isStreaming}
          className="flex h-12 w-12 items-center justify-center rounded-lg bg-primary-600 text-white hover:bg-primary-700 disabled:opacity-50"
        >
          <Send className="h-5 w-5" />
        </button>
      </div>
    </div>
  );
}
