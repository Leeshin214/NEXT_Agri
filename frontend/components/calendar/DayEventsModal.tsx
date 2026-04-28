'use client';

import { useMemo } from 'react';
import { Plus } from 'lucide-react';
import Modal from '@/components/common/Modal';
import {
  getCalendarEventColorClass,
  getCalendarEventLabel,
} from '@/constants/status';
import { cn } from '@/lib/utils';
import { formatKoreanDateWithWeekday } from '@/lib/date';
import type { CalendarEvent } from '@/types';

interface DayEventsModalProps {
  date: string | null;
  events: CalendarEvent[];
  onClose: () => void;
  onSelectEvent: (event: CalendarEvent) => void;
  onAddEvent: (date: string) => void;
  role: 'seller' | 'buyer';
}

function formatTime(t: string | null): string | null {
  if (!t) return null;
  return t.length >= 5 ? t.slice(0, 5) : t;
}

function getEventTimeText(ev: CalendarEvent): string {
  const start = formatTime(ev.start_time);
  const end = formatTime(ev.end_time);
  if (start && end) return `${start} ~ ${end}`;
  if (start) return start;
  return '종일';
}

export default function DayEventsModal({
  date,
  events,
  onClose,
  onSelectEvent,
  onAddEvent,
  // role prop은 추후 역할별 라벨 분기에 사용할 수 있어 받아두지만 현재는 미사용
  role: _role,
}: DayEventsModalProps) {
  void _role;

  // start_time 오름차순 정렬 (없으면 마지막) — null/undefined 안전 비교
  const sortedDayEvents = useMemo(() => {
    return [...events].sort((a, b) => {
      const aHas = !!a.start_time;
      const bHas = !!b.start_time;
      if (aHas && !bHas) return -1;
      if (!aHas && bHas) return 1;
      const aStart = a.start_time ?? '';
      const bStart = b.start_time ?? '';
      return aStart.localeCompare(bStart);
    });
  }, [events]);

  const isOpen = !!date;

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={date ? formatKoreanDateWithWeekday(date) : '일정 목록'}
      size="md"
      footer={
        <>
          <button
            type="button"
            onClick={() => {
              if (date) onAddEvent(date);
            }}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700"
          >
            <Plus className="h-4 w-4" aria-hidden="true" />
            일정 추가
          </button>
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
      {sortedDayEvents.length === 0 ? (
        <div className="py-8 text-center">
          <p className="text-sm text-gray-500">
            이 날짜에 등록된 일정이 없습니다
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {sortedDayEvents.map((ev) => {
            const main = ev.product_name ?? ev.title;
            const sub = ev.order_number;
            const typeLabel = getCalendarEventLabel(ev);
            const timeText = getEventTimeText(ev);
            return (
              <button
                key={ev.id}
                type="button"
                onClick={() => onSelectEvent(ev)}
                className="block w-full rounded-lg border border-gray-200 p-3 text-left transition-colors hover:bg-gray-50"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <div
                        className={cn(
                          'h-2.5 w-2.5 flex-shrink-0 rounded-full',
                          getCalendarEventColorClass(ev)
                        )}
                      />
                      <span className="truncate text-sm font-medium text-gray-900">
                        {main}
                      </span>
                    </div>
                    {sub && (
                      <p className="ml-4 mt-0.5 truncate text-xs text-gray-500">
                        {sub}
                      </p>
                    )}
                  </div>
                  {typeLabel && (
                    <span className="flex-shrink-0 rounded-full bg-gray-100 px-2 py-0.5 text-[10px] text-gray-600">
                      {typeLabel}
                    </span>
                  )}
                </div>
                <p className="mt-2 text-xs text-gray-400">{timeText}</p>
              </button>
            );
          })}
        </div>
      )}
    </Modal>
  );
}
