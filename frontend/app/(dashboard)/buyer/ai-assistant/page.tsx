'use client';

import { useState, useRef, useEffect } from 'react';
import { Send, Sparkles, AlertTriangle } from 'lucide-react';
import PageHeader from '@/components/common/PageHeader';
import { useAIStream } from '@/hooks/useAIStream';
import { useAIHistory } from '@/hooks/useAIHistory';
import { useAIChatStore } from '@/store/aiChatStore';
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
  const { isStreaming, manualReview, stream } = useAIStream();
  // useAIHistory 는 fetch + store hydrate 트리거용 — data 자체는 안 씀
  useAIHistory(100);
  const turns = useAIChatStore((s) => s.turns);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const lastTurn = turns.length > 0 ? turns[turns.length - 1] : null;
  const showManualReviewBanner =
    manualReview && !!lastTurn && !lastTurn.pending;

  // turns 변경 또는 마지막 turn 응답 변화 시 하단 스크롤
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [turns.length, lastTurn?.response]);

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

      {/* 대화 영역 — 캐시된 turns 모두 표시 */}
      <div className="mb-4 min-h-[300px] max-h-[60vh] overflow-y-auto rounded-xl bg-white p-6 shadow-sm">
        {turns.length === 0 ? (
          <div className="flex h-[250px] items-center justify-center text-sm text-gray-400">
            질문을 입력하거나 빠른 프롬프트를 선택하세요
          </div>
        ) : (
          <div className="space-y-2">
            {turns.map((turn, idx) => {
              const dateLabel = toDateLabel(turn.created_at);
              const prevDateLabel =
                idx > 0 ? toDateLabel(turns[idx - 1].created_at) : null;
              const showDivider = dateLabel !== prevDateLabel;
              const isLastPending =
                idx === turns.length - 1 && turn.pending && turn.response === '';

              return (
                <div key={turn.id}>
                  {showDivider && <DateDivider label={dateLabel} />}

                  {/* 사용자 메시지 — 오른쪽 */}
                  <div className="flex justify-end mb-2">
                    <div className="max-w-[75%] rounded-2xl bg-primary-100 px-4 py-2 text-sm text-primary-900">
                      {turn.prompt}
                    </div>
                  </div>

                  {/* MANUAL_REVIEW 배너 — 마지막 turn 응답 직후에만 */}
                  {idx === turns.length - 1 && showManualReviewBanner && (
                    <div className="bg-yellow-50 border border-yellow-400 rounded p-3 mb-2 flex items-center gap-2">
                      <AlertTriangle
                        className="h-4 w-4 text-yellow-500 flex-shrink-0"
                        aria-hidden="true"
                      />
                      <span className="text-yellow-800 text-sm">
                        AI 답변 검토 필요 — 처리 중 이상이 감지됐습니다. 결과를 직접 확인해 주세요.
                      </span>
                    </div>
                  )}

                  {/* AI 응답 — 왼쪽 */}
                  <div className="flex justify-start mb-2">
                    <div className="max-w-[75%] rounded-2xl bg-gray-100 px-4 py-2 text-sm text-gray-800 whitespace-pre-wrap">
                      {isLastPending ? (
                        <span className="inline-block h-4 w-1 animate-pulse bg-primary-600" />
                      ) : (
                        <>
                          {turn.response}
                          {idx === turns.length - 1 && isStreaming && (
                            <span className="inline-block h-4 w-1 animate-pulse bg-primary-600 ml-0.5" />
                          )}
                        </>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}

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
