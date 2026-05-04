'use client';

import { useState } from 'react';
import Modal from '@/components/common/Modal';
import { useCreateCancelRequest } from '@/hooks/useOrders';

interface CancelRequestModalProps {
  isOpen: boolean;
  onClose: () => void;
  orderId: string;
  orderNumber: string;
}

export default function CancelRequestModal({
  isOpen,
  onClose,
  orderId,
  orderNumber,
}: CancelRequestModalProps) {
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const createMutation = useCreateCancelRequest(orderId);

  const handleClose = () => {
    setReason('');
    setError(null);
    onClose();
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const trimmed = reason.trim();
    if (!trimmed) {
      setError('취소 요청 사유를 입력해 주세요.');
      return;
    }
    try {
      await createMutation.mutateAsync({ reason: trimmed });
      handleClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : '요청에 실패했습니다.');
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      title={`취소 요청 — ${orderNumber}`}
      size="sm"
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <p className="text-sm text-gray-600">
          취소 요청을 보내면 판매자가 승인해야 취소됩니다. 거절될 수도 있습니다.
        </p>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            취소 요청 사유 *
          </label>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={4}
            placeholder="예: 내부 일정 변경으로 주문 취소 요청드립니다."
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
          />
        </div>

        {error && (
          <p className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">{error}</p>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={handleClose}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm hover:bg-gray-50"
          >
            돌아가기
          </button>
          <button
            type="submit"
            disabled={createMutation.isPending}
            className="rounded-lg bg-orange-600 px-4 py-2 text-sm text-white hover:bg-orange-700 disabled:opacity-50"
          >
            {createMutation.isPending ? '요청 중...' : '취소 요청 보내기'}
          </button>
        </div>
      </form>
    </Modal>
  );
}
