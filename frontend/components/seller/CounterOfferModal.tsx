'use client';

import { useEffect, useState } from 'react';
import Modal from '@/components/common/Modal';
import { useSubmitCounterOffer } from '@/hooks/useOrders';
import type { CounterOfferCreate } from '@/types';

interface CounterOfferModalProps {
  isOpen: boolean;
  onClose: () => void;
  orderId: string;
  orderNumber: string;
  /** 현재 주문 합계 — placeholder 표시용 (선택) */
  currentTotal?: number | null;
}

/**
 * 협상가 제시 모달.
 * 작업 명세상 우선 단순화 — proposed_total_amount + notes만 입력.
 * proposed_items 항목별 조정은 v2로 미루지만, 백엔드 인터페이스는 그대로 받을 수 있음.
 *
 * 호출 측 가드:
 * - 주문 상태가 QUOTE_REQUESTED 또는 NEGOTIATING 일 때만 모달 오픈 버튼 노출
 * - 양쪽(buyer/seller) 모두 사용 가능
 */
export default function CounterOfferModal({
  isOpen,
  onClose,
  orderId,
  orderNumber,
  currentTotal,
}: CounterOfferModalProps) {
  const [amount, setAmount] = useState('');
  const [notes, setNotes] = useState('');
  const [error, setError] = useState<string | null>(null);

  const submitMutation = useSubmitCounterOffer(orderId);

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
    if (!Number.isFinite(value) || value < 0) {
      setError('협상가는 0 이상의 정수여야 합니다.');
      return;
    }

    const payload: CounterOfferCreate = {
      proposed_total_amount: Math.floor(value),
      notes: notes || undefined,
    };

    try {
      await submitMutation.mutateAsync(payload);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : '협상가 제시에 실패했습니다.');
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={`협상가 제시 — ${orderNumber}`}
      size="md"
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        {currentTotal != null && (
          <div className="flex items-center justify-between rounded-lg bg-gray-50 px-4 py-2">
            <span className="text-xs text-gray-500">현재 합계</span>
            <span className="text-sm font-medium text-gray-700">
              {currentTotal.toLocaleString('ko-KR')}원
            </span>
          </div>
        )}

        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            제시 금액 (원) *
          </label>
          <input
            type="number"
            min={0}
            step={1}
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="예: 1200000"
            required
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
          />
          {amount && Number.isFinite(Number(amount)) && (
            <p className="mt-1 text-xs text-gray-500">
              {Number(amount).toLocaleString('ko-KR')}원
            </p>
          )}
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            메모
          </label>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            placeholder="제시 사유, 조건 등"
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
          />
        </div>

        {error && (
          <p className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">
            {error}
          </p>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm hover:bg-gray-50"
          >
            닫기
          </button>
          <button
            type="submit"
            disabled={submitMutation.isPending}
            className="rounded-lg bg-primary-600 px-4 py-2 text-sm text-white hover:bg-primary-700 disabled:opacity-50"
          >
            {submitMutation.isPending ? '제시 중...' : '협상가 제시'}
          </button>
        </div>
      </form>
    </Modal>
  );
}
