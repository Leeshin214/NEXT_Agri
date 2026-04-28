'use client';

import { useRouter } from 'next/navigation';
import { ExternalLink, Trash2 } from 'lucide-react';
import Modal from '@/components/common/Modal';
import { useDeleteCalendarEvent } from '@/hooks/useCalendar';
import {
  getCalendarEventColorClass,
  getCalendarEventLabel,
} from '@/constants/status';
import { cn } from '@/lib/utils';
import type { CalendarEvent } from '@/types';

interface EventDetailModalProps {
  event: CalendarEvent | null;
  onClose: () => void;
  role: 'seller' | 'buyer';
}

function formatKoreanDate(dateStr: string): string {
  // 'YYYY-MM-DD' → 'YYYY년 M월 D일'
  const [y, m, d] = dateStr.split('-');
  if (!y || !m || !d) return dateStr;
  return `${y}년 ${Number(m)}월 ${Number(d)}일`;
}

function formatTime(t: string | null): string | null {
  if (!t) return null;
  // 'HH:MM:SS' → 'HH:MM'
  return t.length >= 5 ? t.slice(0, 5) : t;
}

export default function EventDetailModal({
  event,
  onClose,
  role,
}: EventDetailModalProps) {
  const router = useRouter();
  const deleteEvent = useDeleteCalendarEvent();

  if (!event) {
    return (
      <Modal isOpen={false} onClose={onClose} title="일정 상세" size="sm">
        <div />
      </Modal>
    );
  }

  const main = event.product_name ?? event.title;
  const sub = event.order_number;
  const typeLabel = getCalendarEventLabel(event);

  // 정기배송 가상 이벤트(`sub-virtual-...`)는 DB row 가 없으므로 삭제 불가.
  // 캘린더 페이지에서 합성한 가상 이벤트는 event_type === 'SUBSCRIPTION' 또는 id prefix 로 식별.
  const isVirtual =
    event.event_type === 'SUBSCRIPTION' ||
    event.id.startsWith('sub-virtual-');

  const startLabel = formatTime(event.start_time);
  const endLabel = formatTime(event.end_time);
  const timeText =
    startLabel && endLabel
      ? `${startLabel} ~ ${endLabel}`
      : startLabel
        ? startLabel
        : '종일';

  const handleDelete = async () => {
    if (!confirm('이 일정을 삭제하시겠습니까?')) return;
    try {
      await deleteEvent.mutateAsync(event.id);
      onClose();
    } catch {
      // 에러 토스트는 상위에서 처리하지 않으므로 콘솔만
    }
  };

  const handleOpenOrder = () => {
    if (!event.order_id) return;
    const path =
      role === 'buyer'
        ? `/buyer/orders/${event.order_id}`
        : `/seller/orders/${event.order_id}`;
    router.push(path);
  };

  return (
    <Modal
      isOpen={true}
      onClose={onClose}
      title="일정 상세"
      size="sm"
      footer={
        <>
          {!isVirtual && (
            <button
              type="button"
              onClick={handleDelete}
              disabled={deleteEvent.isPending}
              className="inline-flex items-center gap-1.5 rounded-lg border border-red-200 bg-white px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
            >
              <Trash2 className="h-4 w-4" aria-hidden="true" />
              {deleteEvent.isPending ? '삭제 중...' : '삭제'}
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            닫기
          </button>
        </>
      }
    >
      <div className="space-y-4">
        {/* 헤더: 메인 + 서브 */}
        <div>
          <h3 className="text-lg font-semibold text-gray-900">{main}</h3>
          {sub && <p className="mt-0.5 text-xs text-gray-500">{sub}</p>}
        </div>

        {/* 유형 뱃지 + 색상 점 */}
        <div className="flex items-center gap-2">
          <span
            className={cn(
              'inline-block h-2.5 w-2.5 rounded-full',
              getCalendarEventColorClass(event)
            )}
          />
          {typeLabel && (
            <span className="rounded-full bg-gray-100 px-2.5 py-0.5 text-xs text-gray-700">
              {typeLabel}
            </span>
          )}
        </div>

        {/* 날짜 / 시간 */}
        <div className="space-y-1.5 rounded-lg bg-gray-50 p-3">
          <div className="flex items-center justify-between text-sm">
            <span className="text-gray-500">날짜</span>
            <span className="font-medium text-gray-900">
              {formatKoreanDate(event.event_date)}
            </span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-gray-500">시간</span>
            <span className="font-medium text-gray-900">{timeText}</span>
          </div>
        </div>

        {/* 설명 */}
        {event.description && (
          <div>
            <p className="mb-1 text-xs font-medium text-gray-500">설명</p>
            <p className="whitespace-pre-wrap text-sm text-gray-800">
              {event.description}
            </p>
          </div>
        )}

        {/* 주문 상세 보기 */}
        {event.order_id && (
          <button
            type="button"
            onClick={handleOpenOrder}
            className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg border border-primary-200 bg-primary-50 px-4 py-2 text-sm font-medium text-primary-700 hover:bg-primary-100"
          >
            <ExternalLink className="h-4 w-4" aria-hidden="true" />
            주문 상세 보기
          </button>
        )}
      </div>
    </Modal>
  );
}
