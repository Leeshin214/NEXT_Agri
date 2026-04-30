'use client';

import { Suspense, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { ChevronLeft, ChevronRight, Plus, Repeat } from 'lucide-react';
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

/**
 * useSearchParams() 는 Next.js 14 App Router 에서 반드시 Suspense boundary 안에서
 * 사용해야 한다 (그렇지 않으면 빌드 경고 + 페이지 전체가 동적 fallback 으로 강제됨).
 * default export 는 얇은 Suspense wrapper, 실제 로직은 Inner 컴포넌트에 위치.
 */
function BuyerCalendarPageInner() {
  const today = new Date();
  const searchParams = useSearchParams();

  // 외부 진입 (예: 정기배송 D-day 라벨 → /buyer/calendar?date=2026-05-02) 시
  // 해당 월/일에 즉시 도달하도록 초기 상태를 쿼리 기반으로 결정한다.
  // 쿼리 형식: 'YYYY-MM-DD'. 잘못된 형식은 무시 → 오늘 기준.
  const dateParam = searchParams?.get('date') ?? null;
  const parsedQuery = useMemo(() => {
    if (!dateParam) return null;
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateParam);
    if (!m) return null;
    const y = Number(m[1]);
    const mo = Number(m[2]);
    const d = Number(m[3]);
    if (!y || !mo || !d || mo < 1 || mo > 12 || d < 1 || d > 31) return null;
    return { year: y, month: mo, day: d, dateStr: dateParam };
  }, [dateParam]);

  const [year, setYear] = useState(parsedQuery?.year ?? today.getFullYear());
  const [month, setMonth] = useState(parsedQuery?.month ?? today.getMonth() + 1);
  const [selectedDate, setSelectedDate] = useState<string | null>(
    parsedQuery?.dateStr ?? null
  );
  const [selectedEvent, setSelectedEvent] = useState<CalendarEvent | null>(null);
  const [dayModalDate, setDayModalDate] = useState<string | null>(
    parsedQuery?.dateStr ?? null
  );
  const [showModal, setShowModal] = useState(false);

  // 같은 페이지에서 ?date 쿼리만 변하는 케이스 (Next.js 클라이언트 네비게이션) 동기화.
  useEffect(() => {
    if (!parsedQuery) return;
    setYear(parsedQuery.year);
    setMonth(parsedQuery.month);
    setSelectedDate(parsedQuery.dateStr);
    setDayModalDate(parsedQuery.dateStr);
  }, [parsedQuery]);

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

  // V1.6 — 백엔드가 정기배송 ACTIVE 시 양 당사자 calendar_events 에 자동 INSERT 한다.
  // 같은 (subscription_id, event_date) 가 백엔드 응답에 이미 있으면 가상 이벤트 합성을 skip 하여 중복 노출 방지.
  // 백엔드 backfill 안 된 기존 ACTIVE 정기배송에 대해서는 가상 이벤트를 fallback 으로 유지한다.
  const backendSubKeys = useMemo(() => {
    const keys = new Set<string>();
    for (const ev of [...baseMonthEvents, ...baseAllEvents]) {
      if (ev.subscription_id) {
        keys.add(`${ev.subscription_id}|${ev.event_date}`);
      }
    }
    return keys;
  }, [baseMonthEvents, baseAllEvents]);

  // 정기배송 가상 이벤트 — 향후 3개월 분량 (회당 50회 안전상한)
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

        // Dedupe — 백엔드가 이미 동기 INSERT 한 (subscription_id, date) 면 skip.
        if (!backendSubKeys.has(`${sub.id}|${dateStr}`)) {
          events.push({
            id: `sub-virtual-${sub.id}-${round}`,
            user_id: '',
            order_id: null,
            subscription_id: sub.id,
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
        }

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
  }, [activeSubs, backendSubKeys]);

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
    const partner = ev.seller_company ?? ev.seller_name ?? null;
    const sub = partner;
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
      <PageHeader title="캘린더" description="입고 및 미팅 일정을 관리하세요" />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* 달력 */}
        <div className="lg:col-span-8 xl:col-span-9 rounded-xl bg-white p-6 shadow-sm">
          {/* 월 네비게이션 */}
          <div className="mb-5 flex items-center justify-between">
            <div className="flex items-center gap-1">
              <button onClick={prevMonth} className="rounded-lg p-2 hover:bg-gray-100">
                <ChevronLeft className="h-5 w-5" />
              </button>
              {/* 오늘 버튼 — 현재 달로 즉시 이동 */}
              <button
                type="button"
                onClick={() => {
                  setYear(today.getFullYear());
                  setMonth(today.getMonth() + 1);
                }}
                className="rounded px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-100 hover:text-primary-700"
              >
                오늘
              </button>
            </div>
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
            {/* 빈 셀 — 이전 달 영역. 톤 다운된 배경으로 시각적 균일성 확보 */}
            {Array.from({ length: firstDayOfWeek }).map((_, i) => (
              <div key={`empty-${i}`} className="h-28 rounded-lg bg-gray-50/40" />
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
                    'h-28 cursor-pointer overflow-hidden rounded-lg border p-2 transition-colors',
                    selectedDate === dateStr
                      ? 'border-primary-500 bg-primary-50 ring-1 ring-primary-500'
                      : 'border-gray-100 hover:border-gray-200 hover:bg-gray-50'
                  )}
                >
                  <span
                    className={cn(
                      'inline-flex h-7 w-7 items-center justify-center rounded-full text-sm',
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
                      셀에서는 메인 라인만 표시(sub 라인 제거) — 디테일은 모달에서 확인.
                    */}
                    {dayEvents.slice(0, 2).map((ev) => {
                      const { main } = getEventLabels(ev);
                      const isSubscription = !!ev.subscription_id;
                      return (
                        <div
                          key={ev.id}
                          className={cn(
                            'block w-full rounded px-1.5 py-0.5 text-left text-[11px] text-white',
                            getCalendarEventColorClass(ev)
                          )}
                        >
                          <div className="flex items-center gap-1">
                            {isSubscription && (
                              <Repeat
                                className="h-3 w-3 flex-shrink-0"
                                aria-hidden="true"
                              />
                            )}
                            <span className="truncate font-medium">{main}</span>
                          </div>
                        </div>
                      );
                    })}
                    {dayEvents.length > 2 && (
                      <p className="mt-1 rounded bg-gray-100 px-1 py-0.5 text-center text-[11px] font-medium text-gray-600">
                        +{dayEvents.length - 2}개 더보기
                      </p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* 우측 1열 — 전체 일정 */}
        <div className="lg:col-span-4 xl:col-span-3 space-y-4">
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

          <div className="max-h-[calc(100vh-220px)] space-y-4 overflow-y-auto pr-1">
            {groupedEvents.length === 0 ? (
              <p className="text-sm text-gray-500">등록된 일정이 없습니다</p>
            ) : (
              groupedEvents.map(({ date, events }) => (
                <div key={date}>
                  <button
                    type="button"
                    onClick={() => handleListHeaderClick(date)}
                    className="sticky top-0 block w-full border-b-2 border-gray-200 bg-white py-2.5 text-left text-sm font-semibold text-gray-700 hover:text-primary-700"
                  >
                    {formatKoreanDateWithWeekday(date)}
                  </button>
                  <ul className="mt-2 space-y-2">
                    {events.map((ev) => {
                      const { main, sub } = getEventLabels(ev);
                      const typeLabel = getCalendarEventLabel(ev);
                      const isSubscription = !!ev.subscription_id;
                      return (
                        <li key={ev.id}>
                          <button
                            type="button"
                            onClick={() => handleListItemClick(ev)}
                            className={cn(
                              'block w-full rounded-lg border p-3 text-left transition-colors hover:border-gray-200 hover:bg-gray-50',
                              selectedEvent?.id === ev.id
                                ? 'border-primary-300 bg-primary-50'
                                : 'border-gray-100'
                            )}
                          >
                            {/* 메타 라인 — 점·뱃지·정기배송 아이콘·시간 */}
                            <div className="mb-1.5 flex items-center gap-2">
                              <div
                                className={cn(
                                  'h-2 w-2 flex-shrink-0 rounded-full',
                                  getCalendarEventColorClass(ev)
                                )}
                              />
                              {typeLabel && (
                                <span
                                  className={cn(
                                    'flex-shrink-0 rounded-full px-2 py-0.5 text-[11px]',
                                    isSubscription
                                      ? 'bg-purple-100 text-purple-700'
                                      : 'bg-gray-100 text-gray-600'
                                  )}
                                >
                                  {typeLabel}
                                </span>
                              )}
                              {isSubscription && (
                                <Repeat
                                  className="h-3 w-3 flex-shrink-0 text-purple-600"
                                  aria-hidden="true"
                                />
                              )}
                              {ev.start_time && (
                                <span className="ml-auto flex-shrink-0 text-[11px] text-gray-400">
                                  {ev.start_time.slice(0, 5)}
                                  {ev.end_time ? ` ~ ${ev.end_time.slice(0, 5)}` : ''}
                                </span>
                              )}
                            </div>
                            {/* 제목 — 풀폭 */}
                            <p className="truncate text-sm font-medium text-gray-900">
                              {main}
                            </p>
                            {sub && (
                              <p className="mt-0.5 line-clamp-1 text-xs text-gray-500">
                                {sub}
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
        role="buyer"
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
        role="buyer"
      />
    </div>
  );
}

export default function BuyerCalendarPage() {
  return (
    <Suspense
      fallback={
        <div className="py-12 text-center text-sm text-gray-400">
          캘린더 로딩 중...
        </div>
      }
    >
      <BuyerCalendarPageInner />
    </Suspense>
  );
}
