'use client';

import { AlertTriangle } from 'lucide-react';
import type { CancelRequest } from '@/types';
import { useRespondCancelRequest } from '@/hooks/useOrders';

interface CancelRequestPanelProps {
  orderId: string;
  cancelRequest: CancelRequest;
}

export default function CancelRequestPanel({
  orderId,
  cancelRequest,
}: CancelRequestPanelProps) {
  const respondMutation = useRespondCancelRequest(orderId, cancelRequest.id);

  const handleRespond = (action: 'approve' | 'reject') => {
    respondMutation.mutate({ action });
  };

  return (
    <div className="rounded-xl border border-orange-300 bg-orange-50 p-4">
      <div className="mb-2 flex items-center gap-2">
        <AlertTriangle className="h-4 w-4 text-orange-500 flex-shrink-0" />
        <span className="text-sm font-semibold text-orange-800">구매자 취소 요청</span>
      </div>
      <p className="mb-3 text-xs text-orange-700 whitespace-pre-wrap leading-relaxed">
        사유: {cancelRequest.reason}
      </p>
      {respondMutation.isError && (
        <p className="mb-2 text-xs text-red-600">
          {respondMutation.error instanceof Error
            ? respondMutation.error.message
            : '처리에 실패했습니다.'}
        </p>
      )}
      <div className="flex gap-2">
        <button
          onClick={() => handleRespond('approve')}
          disabled={respondMutation.isPending}
          className="flex-1 rounded-lg bg-red-600 px-3 py-2 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50"
        >
          {respondMutation.isPending ? '처리 중...' : '취소 승인'}
        </button>
        <button
          onClick={() => handleRespond('reject')}
          disabled={respondMutation.isPending}
          className="flex-1 rounded-lg border border-gray-300 bg-white px-3 py-2 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
        >
          {respondMutation.isPending ? '처리 중...' : '거절'}
        </button>
      </div>
    </div>
  );
}
