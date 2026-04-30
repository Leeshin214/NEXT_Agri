'use client';

import { useEffect, useRef, useState } from 'react';
import { Calendar, X } from 'lucide-react';
import { useSubmitDeliveryDateChange } from '@/hooks/useDeliveryDateChanges';
import { cn } from '@/lib/utils';
import type { OrderStatus } from '@/types';

interface DeliveryDatePopoverProps {
  roomId: string | null;
  /** 채팅방에 연결된 주문 id. 없으면 버튼 비활성화 */
  orderId: string | null;
  /** 현재 주문 상태 — PREPARING 이상이면 비활성화 */
  orderStatus?: OrderStatus | null;
  /** 현재 주문의 납품일 — 동일 날짜 제출 차단 + placeholder 표시용 */
  currentDeliveryDate?: string | null;
}

/**
 * 채팅 입력창 좌측 (PriceOfferPopover 우측) 에 배치되는
 * "납품일 변경 요청" 버튼 + 팝오버 입력 폼.
 *
 * - room.order_id 가 없으면 버튼 비활성화
 * - 주문 상태가 변경 가능 상태(QUOTE_REQUESTED/NEGOTIATING/CONFIRMED) 가 아니면 비활성화
 * - 제출 → useSubmitDeliveryDateChange(orderId).mutate(...)
 * - 성공 시 팝오버 자동 닫기, 입력값 초기화
 */

const CHANGEABLE_STATUSES: OrderStatus[] = [
  'QUOTE_REQUESTED',
  'NEGOTIATING',
  'CONFIRMED',
];

function todayISO(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '미정';
  try {
    return new Date(iso).toLocaleDateString('ko-KR', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    });
  } catch {
    return iso;
  }
}

export default function DeliveryDatePopover({
  roomId,
  orderId,
  orderStatus,
  currentDeliveryDate,
}: DeliveryDatePopoverProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [proposedDate, setProposedDate] = useState('');
  const [notes, setNotes] = useState('');
  const [error, setError] = useState<string | null>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);

  const submitMutation = useSubmitDeliveryDateChange(orderId ?? '');

  const isChangeable = orderStatus
    ? CHANGEABLE_STATUSES.includes(orderStatus)
    : true; // 모르면 일단 허용 → 백엔드가 422 로 차단

  const disabled = !roomId || !orderId || !isChangeable;
  const tooltip = !roomId
    ? '채팅방을 먼저 선택하세요'
    : !orderId
    ? '이 채팅방에 연결된 주문이 없습니다'
    : !isChangeable
    ? '출하 준비 중이라 납품일을 변경할 수 없습니다'
    : '납품일 변경 요청';

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
      setProposedDate('');
      setNotes('');
      setError(null);
    }
  }, [isOpen]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!proposedDate) {
      setError('변경할 날짜를 선택하세요');
      return;
    }
    if (proposedDate < todayISO()) {
      setError('오늘 이후 날짜만 선택할 수 있습니다');
      return;
    }
    if (currentDeliveryDate && proposedDate === currentDeliveryDate) {
      setError('현재 납품일과 다른 날짜를 선택하세요');
      return;
    }

    try {
      await submitMutation.mutateAsync({
        proposed_delivery_date: proposedDate,
        notes: notes || undefined,
      });
      setIsOpen(false);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : '납품일 변경 요청에 실패했습니다'
      );
    }
  };

  return (
    <div ref={wrapperRef} className="relative">
      <button
        type="button"
        onClick={() => !disabled && setIsOpen((v) => !v)}
        disabled={disabled}
        title={tooltip}
        aria-label="납품일 변경 요청"
        className={cn(
          'flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg border transition-colors',
          disabled
            ? 'cursor-not-allowed border-gray-200 bg-gray-50 text-gray-300'
            : 'border-sky-300 bg-sky-50 text-sky-700 hover:bg-sky-100'
        )}
      >
        <Calendar className="h-4 w-4" />
      </button>

      {isOpen && !disabled && (
        <div className="absolute bottom-full left-0 z-30 mb-2 w-80 rounded-xl border border-gray-200 bg-white shadow-lg">
          <div className="flex items-center justify-between border-b border-gray-100 px-4 py-2.5">
            <div className="flex items-center gap-1.5">
              <Calendar className="h-4 w-4 text-sky-600" />
              <span className="text-sm font-semibold text-gray-900">
                납품일 변경 요청
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
            <div className="flex items-center justify-between rounded-md bg-gray-50 px-3 py-1.5 text-xs">
              <span className="text-gray-500">현재 납품일</span>
              <span className="font-medium text-gray-700">
                {formatDate(currentDeliveryDate)}
              </span>
            </div>

            <div>
              <label className="mb-1 block text-xs font-medium text-gray-700">
                새 납품일 *
              </label>
              <input
                type="date"
                min={todayISO()}
                value={proposedDate}
                onChange={(e) => setProposedDate(e.target.value)}
                required
                autoFocus
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
              />
            </div>

            <div>
              <label className="mb-1 block text-xs font-medium text-gray-700">
                메모
              </label>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={2}
                placeholder="변경 사유 등 (선택)"
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
                {submitMutation.isPending ? '요청 중...' : '변경 요청'}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
