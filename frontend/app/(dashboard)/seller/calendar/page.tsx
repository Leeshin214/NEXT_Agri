'use client';

import { useMemo, useState } from 'react';
import { ChevronLeft, ChevronRight, Plus } from 'lucide-react';
import PageHeader from '@/components/common/PageHeader';
import Modal from '@/components/common/Modal';
import EventDetailModal from '@/components/calendar/EventDetailModal';
import DayEventsModal from '@/components/calendar/DayEventsModal';
import { useCalendarEvents, useCreateCalendarEvent } from '@/hooks/useCalendar';
import { useSubscriptions } from '@/hooks/useSubscriptions';
import { EVENT_TYPE_OPTIONS } from '@/constants/options';
import {
  getCalendarEventColorClass,
  getCalendarEventLabel,
} from '@/constants/status';
import { formatKoreanDateWithWeekday } from '@/lib/date';
import type { CalendarEvent, CalendarEventCreate, EventType } from '@/types';
import { cn } from '@/lib/utils';

export default function SellerCalendarPage() {
  const today = new Date();
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth() + 1);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [selectedEvent, setSelectedEvent] = useState<CalendarEvent | null>(null);
  const [dayModalDate, setDayModalDate] = useState<string | null>(null);
  const [showModal, setShowModal] = useState(false);

  // 캘린더 그리드 — 현재 월에 한정
  const { data: monthData } = useCalendarEvents(year, month);
  // 우측 "전체 일정" 리스트 — 전체 월
  const { data: allData } = useCalendarEvents();
  // 정기배송 — 본인 ACTIVE 정기배송만 가상 이벤트로 합성
  const { data: subData } = useSubscriptions({ status: 'ACTIVE', limit: 200 });
  const createEvent = useCreateCalendarEvent();
  const monthEvents = monthData?.data ?? [];
  const allEvents = allData?.data ?? [];
  const activeSubs = subData?.data ?? [];

  // CANCELLED 주문 일정은 백엔드 soft-delete 사이드 케이스 방어 — 어디서도 표시하지 않는다.
  const baseMonthEvents = useMemo(
    () => monthEvents.filter((e) => e.order_status !== 'CANCELLED'),
    [monthEvents]
  );
  const baseAllEvents = useMemo(
    () => allEvents.filter((e) => e.order_status !== 'CANCELLED'),
    [allEvents]
  );

  // 정기배송 가상 이벤트 — 향후 3개월 분량 (회당 12회 안전상한)
  // event_id 는 'sub-virtual-{subId}-{round}' 로 충돌 회피.
  // user_id/order_id 는 빈 문자열/null — 가상 이벤트라 식별 불필요.
  const subscriptionVirtualEvents: CalendarEvent[] = useMemo(() => {
    const events: CalendarEvent[] = [];
    const now = new Date();
    const horizon = new Date(now.getFullYear(), now.getMonth() + 3, 0); // 약 3개월

    for (const sub of activeSubs) {
      const cur = new Date(sub.next_delivery_date);
      let round = 1;
      while (cur <= horizon && round <= 50) {
        const dateStr = `${cur.getFullYear()}-${String(
          cur.getMonth() + 1
        ).padStart(2, '0')}-${String(cur.getDate()).padStart(2, '0')}`;
        events.push({
          id: `sub-virtual-${sub.id}-${round}`,
          user_id: '',
          order_id: null,
          title: '정기배송 예정',
          event_type: 'SUBSCRIPTION',
          event_date: dateStr,
          start_time: null,
          end_time: null,
          description: `정기배송 ${round}회차 — ${
            sub.items[0]?.product_name ?? '상품'
          }${sub.items.length > 1 ? ` 외 ${sub.items.length - 1}건` : ''}`,
          is_allday: true,
          created_at: '',
          order_number: null,
          product_name: sub.items[0]?.product_name ?? '정기배송',
          order_status: null,
        });

        if (sub.frequency === 'WEEKLY') cur.setDate(cur.getDate() + 7);
        else if (sub.frequency === 'BIWEEKLY') cur.setDate(cur.getDate() + 14);
        else if (sub.frequency === 'MONTHLY') {
          cur.setMonth(cur.getMonth() + 1);
          if (sub.day_of_month) {
            const lastDay = new Date(
              cur.getFullYear(),
              cur.getMonth() + 1,
              0
            ).getDate();
            cur.setDate(Math.min(sub.day_of_month, lastDay));
          }
        }
        round += 1;
      }
    }
    return events;
  }, [activeSubs]);

  const visibleMonthEvents = useMemo(
    () => [...baseMonthEvents, ...subscriptionVirtualEvents],
    [baseMonthEvents, subscriptionVirtualEvents]
  );
  const visibleAllEvents = useMemo(
    () => [...baseAllEvents, ...subscriptionVirtualEvents],
    [baseAllEvents, subscriptionVirtualEvents]
  );

  const daysInMonth = new Date(year, month, 0).getDate();
  const firstDayOfWeek = new Date(year, month - 1, 1).getDay();
  const days = Array.from({ length: daysInMonth }, (_, i) => i + 1);

  // 셀과 비교용 dateStr 은 timezone 영향 없는 순수 문자열 조합으로 통일.
  // event_date 는 백엔드가 'YYYY-MM-DD' 문자열로 내려주므로 양쪽이 정확히 일치한다.
  const buildDateStr = (d: number) =>
    `${year}-${String(month).padStart(2, '0')}-${String(d).padStart(2, '0')}`;

  // 같은 날짜 내에서는 우측 리스트/DayEventsModal과 동일하게 start_time 오름차순 정렬.
  // 정렬 없이 백엔드 응답 순서대로 노출하면 셀 첫 N개와 리스트 첫 N개가 어긋나
  // "리스트엔 있는데 셀엔 없는" 일정이 발생한다.
  const getEventsForDateStr = (dateStr: string): CalendarEvent[] =>
    visibleMonthEvents
      .filter((e) => e.event_date === dateStr)
      .sort((a, b) => (a.start_time ?? '').localeCompare(b.start_time ?? ''));

  const getEventsForDay = (day: number): CalendarEvent[] =>
    getEventsForDateStr(buildDateStr(day));

  const prevMonth = () => {
    if (month === 1) { setYear(year - 1); setMonth(12); }
    else setMonth(month - 1);
  };
  const nextMonth = () => {
    if (month === 12) { setYear(year + 1); setMonth(1); }
    else setMonth(month + 1);
  };

  // 우측 리스트는 모든 월의 일정을 날짜별로 그룹화 — 날짜 오름차순 + 그룹 내부 start_time 오름차순.
  const groupedEvents = useMemo(() => {
    const groups = new Map<string, CalendarEvent[]>();
    for (const ev of visibleAllEvents) {
      const list = groups.get(ev.event_date) ?? [];
      list.push(ev);
      groups.set(ev.event_date, list);
    }
    return Array.from(groups.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([date, list]) => ({
        date,
        events: list.sort((a, b) =>
          (a.start_time ?? '').localeCompare(b.start_time ?? '')
        ),
      }));
  }, [visibleAllEvents]);

  const getEventLabels = (ev: CalendarEvent) => {
    const main = ev.product_name ?? ev.title;
    const sub = ev.order_number;
    return { main, sub };
  };

  // 우측 리스트 카드 클릭 — 해당 일정의 월로 이동 + EventDetailModal 오픈.
  const handleListItemClick = (ev: CalendarEvent) => {
    const [y, m] = ev.event_date.split('-').map(Number);
    if (y && m) {
      setYear(y);
      setMonth(m);
    }
    setSelectedDate(ev.event_date);
    setSelectedEvent(ev);
  };

  // 우측 리스트 날짜 헤더 클릭 — 그 날짜로 이동 + DayEventsModal 오픈.
  const handleListHeaderClick = (date: string) => {
    const [y, m] = date.split('-').map(Number);
    if (y && m) {
      setYear(y);
      setMonth(m);
    }
    setSelectedDate(date);
    setDayModalDate(date);
  };

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
              <div key={`empty-${i}`} className="min-h-[100px] md:min-h-[110px]" />
            ))}
            {days.map((day) => {
              const dateStr = buildDateStr(day);
              const dayEvents = getEventsForDay(day);
              const isToday =
                day === today.getDate() &&
                month === today.getMonth() + 1 &&
                year === today.getFullYear();

              return (
                <div
                  key={day}
                  onClick={() => {
                    setSelectedDate(dateStr);
                    setDayModalDate(dateStr);
                  }}
                  className={cn(
                    'min-h-[100px] md:min-h-[110px] cursor-pointer rounded-lg border p-1.5 transition-colors',
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
                    {/*
                      셀 안 일정은 클릭 핸들러 없는 단순 표시 div.
                      어디를 누르든 셀 onClick 으로 위임되어 DayEventsModal 만 오픈.
                      EventDetailModal 은 DayEventsModal 카드 또는 우측 리스트에서만 진입.
                    */}
                    {dayEvents.slice(0, 3).map((ev) => {
                      const { main, sub } = getEventLabels(ev);
                      return (
                        <div
                          key={ev.id}
                          className={cn(
                            'block w-full rounded px-1 py-0.5 text-left text-[10px] text-white',
                            getCalendarEventColorClass(ev)
                          )}
                        >
                          <div className="truncate font-medium">{main}</div>
                          {sub && (
                            <div className="truncate text-[9px] text-white/80">
                              {sub}
                            </div>
                          )}
                        </div>
                      );
                    })}
                    {dayEvents.length > 3 && (
                      <p className="mt-0.5 rounded bg-gray-200 px-1 py-0.5 text-center text-[10px] font-semibold text-gray-700">
                        +{dayEvents.length - 3}개 더보기
                      </p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* 전체 일정 — 모든 월, 날짜별 그룹 */}
        <div className="rounded-xl bg-white p-6 shadow-sm">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="font-semibold text-gray-900">전체 일정</h3>
            <button
              onClick={() => {
                if (!selectedDate) {
                  const todayStr = `${year}-${String(month).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
                  setSelectedDate(todayStr);
                }
                setShowModal(true);
              }}
              className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary-600 text-white hover:bg-primary-700"
              aria-label="일정 추가"
            >
              <Plus className="h-4 w-4" />
            </button>
          </div>

          <div className="max-h-[calc(100vh-260px)] space-y-4 overflow-y-auto pr-1">
            {groupedEvents.length === 0 ? (
              <p className="text-sm text-gray-500">등록된 일정이 없습니다</p>
            ) : (
              groupedEvents.map(({ date, events }) => (
                <div key={date}>
                  <button
                    type="button"
                    onClick={() => handleListHeaderClick(date)}
                    className="sticky top-0 block w-full border-b border-gray-100 bg-white py-2 text-left text-sm font-semibold text-gray-700 hover:text-primary-700"
                  >
                    {formatKoreanDateWithWeekday(date)}
                  </button>
                  <ul className="mt-2 space-y-2">
                    {events.map((ev) => {
                      const { main, sub } = getEventLabels(ev);
                      const typeLabel = getCalendarEventLabel(ev);
                      return (
                        <li key={ev.id}>
                          <button
                            type="button"
                            onClick={() => handleListItemClick(ev)}
                            className={cn(
                              'block w-full rounded-lg border p-3 text-left transition-colors hover:bg-gray-50',
                              selectedEvent?.id === ev.id
                                ? 'border-primary-300 bg-primary-50'
                                : 'border-gray-100'
                            )}
                          >
                            <div className="flex items-start justify-between gap-2">
                              <div className="min-w-0 flex-1">
                                <div className="flex items-center gap-2">
                                  <div
                                    className={cn(
                                      'h-2 w-2 flex-shrink-0 rounded-full',
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
                            {ev.start_time && (
                              <p className="mt-2 text-xs text-gray-400">
                                {ev.start_time.slice(0, 5)}
                                {ev.end_time ? ` ~ ${ev.end_time.slice(0, 5)}` : ''}
                              </p>
                            )}
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              ))
            )}
          </div>
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

      {/* 일정 상세 모달 */}
      <EventDetailModal
        event={selectedEvent}
        onClose={() => setSelectedEvent(null)}
        role="seller"
      />

      {/* 날짜 셀 클릭 — 그날의 전체 일정 모달 */}
      <DayEventsModal
        date={dayModalDate}
        events={dayModalDate ? getEventsForDateStr(dayModalDate) : []}
        onClose={() => setDayModalDate(null)}
        onSelectEvent={(ev) => {
          setDayModalDate(null);
          setSelectedEvent(ev);
        }}
        onAddEvent={(d) => {
          setDayModalDate(null);
          setSelectedDate(d);
          setShowModal(true);
        }}
        role="seller"
      />
    </div>
  );
}
