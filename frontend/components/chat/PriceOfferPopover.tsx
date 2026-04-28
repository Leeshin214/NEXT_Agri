'use client';

import { useEffect, useRef, useState } from 'react';
import { DollarSign, X } from 'lucide-react';
import { useSubmitCounterOfferViaChat } from '@/hooks/useChat';
import { cn } from '@/lib/utils';

interface PriceOfferPopoverProps {
  roomId: string | null;
  /** 채팅방에 연결된 주문 id. 없으면 버튼 비활성화 */
  orderId: string | null;
  /** 현재 주문 합계 — placeholder 표시용 (선택) */
  currentTotal?: number | null;
}

/**
 * 채팅 입력창 좌측에 배치되는 "가격 제시" 버튼 + 팝오버 입력 모달.
 * 클릭 시 작은 팝오버가 떠서 proposed_total_amount + notes 를 입력받는다.
 *
 * - room.order_id 가 없으면 버튼 비활성화 + tooltip 안내
 * - 제출 → useSubmitCounterOfferViaChat(roomId).mutate(...)
 * - 성공 시 팝오버 자동 닫기, 입력값 초기화
 */
export default function PriceOfferPopover({
  roomId,
  orderId,
  currentTotal,
}: PriceOfferPopoverProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [amount, setAmount] = useState('');
  const [notes, setNotes] = useState('');
  const [error, setError] = useState<string | null>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);

  const submitMutation = useSubmitCounterOfferViaChat(roomId);

  const disabled = !roomId || !orderId;
  const tooltip = !roomId
    ? '채팅방을 먼저 선택하세요'
    : !orderId
    ? '이 채팅방에 연결된 주문이 없습니다'
    : '가격 제시';

  // 외부 클릭 시 팝오버 닫기
  useEffect(() => {
    if (!isOpen) return;
    const handleClick = (e: MouseEvent) => {
      if (
        wrapperRef.current &&
        !wrapperRef.current.contains(e.target as Node)
      ) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [isOpen]);

  // 팝오버 열릴 때마다 입력값 초기화
  useEffect(() => {
    if (isOpen) {
      setAmount('');
      setNotes('');
      setError(null);
    }
  }, [isOpen]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    const value = Number(amount);
    if (!Number.isFinite(value) || value <= 0) {
      setError('0보다 큰 정수를 입력하세요');
      return;
    }

    try {
      await submitMutation.mutateAsync({
        proposed_total_amount: Math.floor(value),
        notes: notes || undefined,
      });
      setIsOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : '협상가 제시에 실패했습니다');
    }
  };

  return (
    <div ref={wrapperRef} className="relative">
      <button
        type="button"
        onClick={() => !disabled && setIsOpen((v) => !v)}
        disabled={disabled}
        title={tooltip}
        aria-label="가격 제시"
        className={cn(
          'flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg border transition-colors',
          disabled
            ? 'cursor-not-allowed border-gray-200 bg-gray-50 text-gray-300'
            : 'border-amber-300 bg-amber-50 text-amber-700 hover:bg-amber-100'
        )}
      >
        <DollarSign className="h-4 w-4" />
      </button>

      {isOpen && !disabled && (
        <div className="absolute bottom-full left-0 z-30 mb-2 w-80 rounded-xl border border-gray-200 bg-white shadow-lg">
          <div className="flex items-center justify-between border-b border-gray-100 px-4 py-2.5">
            <div className="flex items-center gap-1.5">
              <DollarSign className="h-4 w-4 text-amber-600" />
              <span className="text-sm font-semibold text-gray-900">
                가격 제시
              </span>
            </div>
            <button
              type="button"
              onClick={() => setIsOpen(false)}
              className="flex h-6 w-6 items-center justify-center rounded-md text-gray-400 hover:bg-gray-100"
              aria-label="닫기"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>

          <form onSubmit={handleSubmit} className="space-y-3 p-4">
            {typeof currentTotal === 'number' && (
              <div className="flex items-center justify-between rounded-md bg-gray-50 px-3 py-1.5 text-xs">
                <span className="text-gray-500">현재 합계</span>
                <span className="font-medium text-gray-700">
                  {currentTotal.toLocaleString('ko-KR')}원
                </span>
              </div>
            )}

            <div>
              <label className="mb-1 block text-xs font-medium text-gray-700">
                제시 금액 *
              </label>
              <input
                type="number"
                min={1}
                step={1}
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="예: 1200000"
                required
                autoFocus
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
              />
              {amount && Number.isFinite(Number(amount)) && Number(amount) > 0 && (
                <p className="mt-1 text-[11px] text-gray-500">
                  {Number(amount).toLocaleString('ko-KR')}원
                </p>
              )}
            </div>

            <div>
              <label className="mb-1 block text-xs font-medium text-gray-700">
                메모
              </label>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={2}
                placeholder="제시 사유, 조건 등 (선택)"
                className="w-full resize-none rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
              />
            </div>

            {error && (
              <p className="rounded-md bg-red-50 px-2.5 py-1.5 text-[11px] text-red-700">
                {error}
              </p>
            )}

            <div className="flex justify-end gap-2 pt-1">
              <button
                type="button"
                onClick={() => setIsOpen(false)}
                className="rounded-md border border-gray-300 px-3 py-1.5 text-xs hover:bg-gray-50"
              >
                취소
              </button>
              <button
                type="submit"
                disabled={submitMutation.isPending}
                className="rounded-md bg-primary-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50"
              >
                {submitMutation.isPending ? '제시 중...' : '가격 제시'}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
