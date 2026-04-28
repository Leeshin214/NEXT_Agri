'use client';

import { useState, useRef, useEffect } from 'react';
import { Send, Sparkles, AlertTriangle } from 'lucide-react';
import PageHeader from '@/components/common/PageHeader';
import { useAIStream } from '@/hooks/useAIStream';
import { useAIHistory } from '@/hooks/useAIHistory';
import { buyerQuickPrompts } from '@/constants/aiPrompts';

// 날짜 문자열(ISO)에서 YYYY-MM-DD 추출
function toDateLabel(isoString: string): string {
  return isoString.slice(0, 10);
}

// 날짜 구분선 컴포넌트
function DateDivider({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3 my-4">
      <div className="flex-1 h-px bg-gray-200" />
      <span className="text-xs text-gray-400 whitespace-nowrap">{label}</span>
      <div className="flex-1 h-px bg-gray-200" />
    </div>
  );
}

export default function BuyerAIAssistantPage() {
  const [input, setInput] = useState('');
  const { response, isStreaming, manualReview, stream } = useAIStream();
  const { data: historyData } = useAIHistory(50);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const history = historyData?.data ?? [];
  // 히스토리는 최신순으로 내려오므로 오래된순으로 뒤집어 표시
  const sortedHistory = [...history].reverse();

  // 새 응답이 올 때마다 하단 스크롤
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [response, history.length]);

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

      {/* 대화 영역 — 히스토리 + 현재 응답 */}
      <div className="mb-4 min-h-[300px] max-h-[60vh] overflow-y-auto rounded-xl bg-white p-6 shadow-sm">
        {sortedHistory.length === 0 && !response ? (
          <div className="flex h-[250px] items-center justify-center text-sm text-gray-400">
            질문을 입력하거나 빠른 프롬프트를 선택하세요
          </div>
        ) : (
          <div className="space-y-2">
            {/* 과거 대화 히스토리 (날짜 구분선 포함) */}
            {sortedHistory.map((conv, idx) => {
              const dateLabel = toDateLabel(conv.created_at);
              const prevDateLabel =
                idx > 0 ? toDateLabel(sortedHistory[idx - 1].created_at) : null;
              const showDivider = dateLabel !== prevDateLabel;

              return (
                <div key={conv.id}>
                  {showDivider && <DateDivider label={dateLabel} />}

                  {/* 사용자 메시지 — 오른쪽 */}
                  <div className="flex justify-end mb-2">
                    <div className="max-w-[75%] rounded-2xl bg-primary-100 px-4 py-2 text-sm text-primary-900">
                      {conv.prompt}
                    </div>
                  </div>

                  {/* AI 응답 — 왼쪽 */}
                  <div className="flex justify-start mb-2">
                    <div className="max-w-[75%] rounded-2xl bg-gray-100 px-4 py-2 text-sm text-gray-800 whitespace-pre-wrap">
                      {conv.response}
                    </div>
                  </div>
                </div>
              );
            })}

            {/* 현재 세션 응답 */}
            {response && (
              <>
                {sortedHistory.length > 0 && (
                  <DateDivider label={toDateLabel(new Date().toISOString())} />
                )}

                {/* MANUAL_REVIEW 배너 — manualReview=true일 때만 표시 */}
                {manualReview && (
                  <div className="bg-yellow-50 border border-yellow-400 rounded p-3 mb-2 flex items-center gap-2">
                    <AlertTriangle className="h-4 w-4 text-yellow-500 flex-shrink-0" aria-hidden="true" />
                    <span className="text-yellow-800 text-sm">
                      AI 답변 검토 필요 — 처리 중 이상이 감지됐습니다. 결과를 직접 확인해 주세요.
                    </span>
                  </div>
                )}

                <div className="prose prose-sm max-w-none whitespace-pre-wrap text-gray-800">
                  {response}
                  {isStreaming && (
                    <span className="inline-block h-4 w-1 animate-pulse bg-primary-600 ml-0.5" />
                  )}
                </div>
              </>
            )}

            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* 입력창 */}
      <div className="flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.nativeEvent.isComposing) return;
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
