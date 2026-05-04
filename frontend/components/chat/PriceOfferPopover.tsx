'use client';

import { useEffect, useRef, useState } from 'react';
import { DollarSign, X } from 'lucide-react';
import { useSubmitCounterOfferViaChat } from '@/hooks/useChat';
import { cn } from '@/lib/utils';

/**
 * 외부(예: NegotiationDraftCard [등록]) 에서 prefill 한 채로 팝오버를 여는 데 쓰는 입력값.
 * 부모가 매번 새 객체를 만들면 useEffect 가 재실행되며 입력값이 덮어써진다 → 부모는
 * 안정 참조(useState 또는 useMemo) 로 전달해야 한다.
 */
export interface PriceOfferPrefill {
  amount?: number;
  notes?: string;
}

interface PriceOfferPopoverProps {
  roomId: string | null;
  /** 채팅방에 연결된 주문 id. 없으면 버튼 비활성화 */
  orderId: string | null;
  /** 현재 주문 합계 — placeholder 표시용 (선택) */
  currentTotal?: number | null;
  /**
   * 외부에서 팝오버를 열면서 입력값을 prefill 할 때 사용. 부모가 객체를 갱신할 때마다
   * 팝오버가 열리고 입력값이 채워진다. null 로 보내면 외부 prefill 영향 없음.
   */
  prefill?: PriceOfferPrefill | null;
  /** prefill 적용 후 부모에게 알려주는 콜백 (선택) — 부모가 prefill 을 null 로 reset 하는 용도 */
  onPrefillConsumed?: () => void;
}

/**
 * 채팅 입력창 좌측에 배치되는 "가격 제시" 버튼 + 팝오버 입력 모달.
 * 클릭 시 작은 팝오버가 떠서 proposed_total_amount + notes 를 입력받는다.
 *
 * - room.order_id 가 없으면 버튼 비활성화 + tooltip 안내
 * - 제출 → useSubmitCounterOfferViaChat(roomId).mutate(...)
 * - 성공 시 팝오버 자동 닫기, 입력값 초기화
 * - prefill prop 이 들어오면 자동으로 팝오버 열고 입력값 채움 (US-2 협상 의도 감지 [등록])
 */
export default function PriceOfferPopover({
  roomId,
  orderId,
  currentTotal,
  prefill,
  onPrefillConsumed,
}: PriceOfferPopoverProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [amount, setAmount] = useState('');
  const [notes, setNotes] = useState('');
  const [error, setError] = useState<string | null>(null);
  // 자체 클릭으로 열렸는지(true) prefill 로 자동으로 열렸는지(false) 구분 — 자동 열림은
  // 다음 isOpen 사이드이펙트에서 입력값을 빈 값으로 reset 하지 않도록 함.
  const openedByPrefillRef = useRef(false);
  const wrapperRef = useRef<HTMLDivElement>(null);

  const submitMutation = useSubmitCounterOfferViaChat(roomId);

  const disabled = !roomId || !orderId;
  const tooltip = !roomId
    ? '채팅방을 먼저 선택하세요'
    : !orderId
    ? '이 채팅방에 연결된 주문이 없습니다'
    : '가격 제시';

  // 외부 prefill 도착 → 팝오버 자동 열기 + 값 채우기 (disabled 면 무시)
  useEffect(() => {
    if (!prefill) return;
    if (disabled) return;
    openedByPrefillRef.current = true;
    setAmount(
      typeof prefill.amount === 'number' && prefill.amount > 0
        ? String(prefill.amount)
        : ''
    );
    setNotes(prefill.notes ?? '');
    setError(null);
    setIsOpen(true);
    onPrefillConsumed?.();
  }, [prefill, disabled, onPrefillConsumed]);

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

  // 팝오버 열릴 때마다 입력값 초기화 (단, prefill 로 열린 경우는 보존)
  useEffect(() => {
    if (!isOpen) return;
    if (openedByPrefillRef.current) {
      // 한 번만 prefill 보존 — 이후 사용자가 닫고 다시 열면 일반 초기화 동작
      openedByPrefillRef.current = false;
      return;
    }
    setAmount('');
    setNotes('');
    setError(null);
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
