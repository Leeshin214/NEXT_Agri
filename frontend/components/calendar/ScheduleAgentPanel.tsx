'use client';

import { Sparkles, CalendarDays, Package, RefreshCw, AlertCircle, Loader2 } from 'lucide-react';
import { useScheduleRecommend } from '@/hooks/useScheduleAgent';
import type { ScheduleRecommendation } from '@/types/scheduleAgent';

interface ScheduleAgentPanelProps {
  year: number;
  month: number;
}

export default function ScheduleAgentPanel({ year, month }: ScheduleAgentPanelProps) {
  const { mutate, data, isPending, isError, error, isIdle } = useScheduleRecommend();

  const result = data?.data;

  return (
    <div className="rounded-xl bg-white p-4 shadow-sm">
      {/* Header */}
      <div className="mb-4 flex items-center gap-2">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-purple-100">
          <Sparkles className="h-4 w-4 text-purple-600" />
        </div>
        <h3 className="font-semibold text-gray-900">AI 일정 추천</h3>
      </div>

      {/* Idle 상태 */}
      {isIdle && (
        <div className="space-y-3">
          <p className="text-sm text-gray-500">
            캘린더, 재고, 주문 데이터를 분석하여 최적의 일정을 추천합니다.
          </p>
          <button
            onClick={() => mutate({ year, month })}
            className="w-full rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 transition-colors"
          >
            추천 받기
          </button>
        </div>
      )}

      {/* 로딩 상태 */}
      {isPending && (
        <div className="flex flex-col items-center gap-3 py-4">
          <Loader2 className="h-6 w-6 animate-spin text-primary-600" />
          <p className="text-sm text-gray-500">AI가 일정을 분석하고 있습니다...</p>
        </div>
      )}

      {/* 에러 상태 */}
      {isError && (
        <div className="space-y-3">
          <div className="flex items-center gap-2 text-red-600">
            <AlertCircle className="h-4 w-4 flex-shrink-0" />
            <p className="text-sm">{error instanceof Error ? error.message : '오류가 발생했습니다.'}</p>
          </div>
          <button
            onClick={() => mutate({ year, month })}
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            다시 시도
          </button>
        </div>
      )}

      {/* 결과 — has_recommendation = true */}
      {result && result.has_recommendation && (
        <div className="space-y-3">
          {result.recommendations.map((rec: ScheduleRecommendation, idx: number) => (
            <div key={idx} className="rounded-lg bg-gray-50 p-3 space-y-1.5">
              <div className="flex items-center gap-1.5">
                <CalendarDays className="h-3.5 w-3.5 text-primary-600 flex-shrink-0" />
                <span className="text-sm font-semibold text-gray-900">{rec.recommended_date}</span>
              </div>
              {rec.product_name && (
                <div className="flex items-center gap-1.5">
                  <Package className="h-3.5 w-3.5 text-gray-400 flex-shrink-0" />
                  <span className="text-xs text-gray-700">
                    {rec.product_name}
                    {rec.recommended_quantity != null && rec.unit && (
                      <span className="ml-1 text-gray-500">
                        {rec.recommended_quantity.toLocaleString()}{rec.unit}
                      </span>
                    )}
                  </span>
                </div>
              )}
              <p className="text-xs text-gray-600">{rec.reasoning}</p>
            </div>
          ))}
          <p className="text-xs text-gray-500">{result.message}</p>
          <button
            onClick={() => mutate({ year, month })}
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            다시 추천 받기
          </button>
        </div>
      )}

      {/* 결과 — has_recommendation = false */}
      {result && !result.has_recommendation && (
        <div className="space-y-3">
          <div className="flex items-start gap-2 text-gray-500">
            <AlertCircle className="h-4 w-4 flex-shrink-0 mt-0.5" />
            <p className="text-sm">{result.message}</p>
          </div>
          <button
            onClick={() => mutate({ year, month })}
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            다시 추천 받기
          </button>
        </div>
      )}
    </div>
  );
}
