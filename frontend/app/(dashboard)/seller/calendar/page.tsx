'use client';

import { useState } from 'react';
import { ChevronLeft, ChevronRight, Plus } from 'lucide-react';
import PageHeader from '@/components/common/PageHeader';
import Modal from '@/components/common/Modal';
import { useCalendarEvents, useCreateCalendarEvent } from '@/hooks/useCalendar';
import { EVENT_TYPE_OPTIONS } from '@/constants/options';
import type { CalendarEvent, CalendarEventCreate, EventType } from '@/types';
import { cn } from '@/lib/utils';
import ScheduleAgentPanel from '@/components/calendar/ScheduleAgentPanel';

const eventTypeColors: Record<string, string> = {
  SHIPMENT: 'bg-blue-500',
  DELIVERY: 'bg-green-500',
  MEETING: 'bg-purple-500',
  QUOTE_DEADLINE: 'bg-red-500',
  ORDER: 'bg-orange-500',
  OTHER: 'bg-gray-500',
};

export default function SellerCalendarPage() {
  const today = new Date();
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth() + 1);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [showModal, setShowModal] = useState(false);

  const { data } = useCalendarEvents(year, month);
  const createEvent = useCreateCalendarEvent();
  const events = data?.data ?? [];

  const daysInMonth = new Date(year, month, 0).getDate();
  const firstDayOfWeek = new Date(year, month - 1, 1).getDay();
  const days = Array.from({ length: daysInMonth }, (_, i) => i + 1);

  const getEventsForDay = (day: number): CalendarEvent[] => {
    const dateStr = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
    return events.filter((e) => e.event_date === dateStr);
  };

  const prevMonth = () => {
    if (month === 1) { setYear(year - 1); setMonth(12); }
    else setMonth(month - 1);
  };
  const nextMonth = () => {
    if (month === 12) { setYear(year + 1); setMonth(1); }
    else setMonth(month + 1);
  };

  const selectedEvents = selectedDate
    ? events.filter((e) => e.event_date === selectedDate)
    : [];

  const handleCreateEvent = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const payload: CalendarEventCreate = {
      title: form.get('title') as string,
      event_type: form.get('event_type') as EventType,
      event_date: selectedDate!,
      description: (form.get('description') as string) || undefined,
    };
    await createEvent.mutateAsync(payload);
    setShowModal(false);
  };

  return (
    <div>
      <PageHeader title="캘린더" description="출하 및 납품 일정을 관리하세요" />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-4">
        {/* 달력 */}
        <div className="lg:col-span-3 rounded-xl bg-white p-6 shadow-sm">
          {/* 월 네비게이션 */}
          <div className="mb-4 flex items-center justify-between">
            <button onClick={prevMonth} className="rounded-lg p-2 hover:bg-gray-100">
              <ChevronLeft className="h-5 w-5" />
            </button>
            <h2 className="text-lg font-semibold text-gray-900">
              {year}년 {month}월
            </h2>
            <button onClick={nextMonth} className="rounded-lg p-2 hover:bg-gray-100">
              <ChevronRight className="h-5 w-5" />
            </button>
          </div>

          {/* 요일 헤더 */}
          <div className="mb-2 grid grid-cols-7 text-center text-xs font-medium text-gray-500">
            {['일', '월', '화', '수', '목', '금', '토'].map((d) => (
              <div key={d} className="py-2">{d}</div>
            ))}
          </div>

          {/* 날짜 그리드 */}
          <div className="grid grid-cols-7 gap-px">
            {/* 빈 셀 */}
            {Array.from({ length: firstDayOfWeek }).map((_, i) => (
              <div key={`empty-${i}`} className="min-h-[80px]" />
            ))}
            {days.map((day) => {
              const dateStr = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
              const dayEvents = getEventsForDay(day);
              const isToday =
                day === today.getDate() &&
                month === today.getMonth() + 1 &&
                year === today.getFullYear();

              return (
                <div
                  key={day}
                  onClick={() => setSelectedDate(dateStr)}
                  className={cn(
                    'min-h-[80px] cursor-pointer rounded-lg border p-1.5 transition-colors',
                    selectedDate === dateStr
                      ? 'border-primary-500 bg-primary-50'
                      : 'border-transparent hover:bg-gray-50'
                  )}
                >
                  <span
                    className={cn(
                      'inline-flex h-6 w-6 items-center justify-center rounded-full text-xs',
                      isToday && 'bg-primary-600 text-white font-bold'
                    )}
                  >
                    {day}
                  </span>
                  <div className="mt-1 space-y-0.5">
                    {dayEvents.slice(0, 2).map((ev) => (
                      <div
                        key={ev.id}
                        className={cn(
                          'truncate rounded px-1 py-0.5 text-[10px] text-white',
                          eventTypeColors[ev.event_type] || 'bg-gray-500'
                        )}
                      >
                        {ev.title}
                      </div>
                    ))}
                    {dayEvents.length > 2 && (
                      <p className="text-[10px] text-gray-400">
                        +{dayEvents.length - 2}개
                      </p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* 선택된 날짜 상세 + AI 추천 */}
        <div className="space-y-6">
        <div className="rounded-xl bg-white p-6 shadow-sm">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="font-semibold text-gray-900">
              {selectedDate || '날짜를 선택하세요'}
            </h3>
            {selectedDate && (
              <button
                onClick={() => setShowModal(true)}
                className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary-600 text-white hover:bg-primary-700"
              >
                <Plus className="h-4 w-4" />
              </button>
            )}
          </div>

          {selectedEvents.length === 0 ? (
            <p className="text-sm text-gray-400">일정이 없습니다.</p>
          ) : (
            <div className="space-y-3">
              {selectedEvents.map((ev) => (
                <div
                  key={ev.id}
                  className="rounded-lg border border-gray-100 p-3"
                >
                  <div className="flex items-center gap-2">
                    <div
                      className={cn(
                        'h-2 w-2 rounded-full',
                        eventTypeColors[ev.event_type]
                      )}
                    />
                    <span className="text-sm font-medium text-gray-900">
                      {ev.title}
                    </span>
                  </div>
                  {ev.description && (
                    <p className="mt-1 text-xs text-gray-500">
                      {ev.description}
                    </p>
                  )}
                  <p className="mt-1 text-xs text-gray-400">
                    {EVENT_TYPE_OPTIONS.find((o) => o.value === ev.event_type)?.label}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
        <ScheduleAgentPanel year={year} month={month} />
        </div>
      </div>

      {/* 일정 추가 모달 */}
      <Modal
        isOpen={showModal}
        onClose={() => setShowModal(false)}
        title="일정 추가"
        size="sm"
      >
        <form onSubmit={handleCreateEvent} className="space-y-4">
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">제목</label>
            <input name="title" required className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500" />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">유형</label>
            <select name="event_type" className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500">
              {EVENT_TYPE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">설명</label>
            <textarea name="description" rows={3} className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500" />
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setShowModal(false)} className="rounded-lg border border-gray-300 px-4 py-2 text-sm hover:bg-gray-50">취소</button>
            <button type="submit" disabled={createEvent.isPending} className="rounded-lg bg-primary-600 px-4 py-2 text-sm text-white hover:bg-primary-700 disabled:opacity-50">
              {createEvent.isPending ? '저장 중...' : '저장'}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
