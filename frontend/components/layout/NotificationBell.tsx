'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  Bell,
  Calendar as CalendarIcon,
  CircleDollarSign,
  MessageCircle,
  Package,
} from 'lucide-react';
import {
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useNotifications,
  useUnreadCount,
} from '@/hooks/useNotifications';
import { useNotificationRealtime } from '@/hooks/useNotificationRealtime';
import { formatRelativeKst } from '@/lib/date';
import type { Notification, NotificationType } from '@/types';

/**
 * 우상단 종(Bell) 알림 드롭다운.
 *
 * - useNotificationRealtime() 을 여기서 한 번만 호출한다 (트리에서 단일 mount).
 *   AppLayout 이나 TopBar 가 별도로 호출하지 말 것 — 중복 구독 발생.
 * - 카운트 뱃지: useUnreadCount() 의 가벼운 폴링 fallback 결과 사용.
 *   목록의 meta.unread_count 와 같은 ['notifications', ...] 키이므로
 *   Realtime / mutation invalidate 시 자동 동기화된다.
 * - 행 클릭: optimistic mark-read → link_url 이 있으면 router.push.
 * - ESC / 외부 클릭으로 닫기.
 */
export default function NotificationBell() {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const router = useRouter();

  // Realtime 구독 — 단일 mount 위치
  useNotificationRealtime();

  const listQuery = useNotifications({ limit: 20 });
  const unreadQuery = useUnreadCount();
  const markRead = useMarkNotificationRead();
  const markAllRead = useMarkAllNotificationsRead();

  const notifications = listQuery.data?.data ?? [];

  // 뱃지 카운트 — unread-count 폴링이 가장 가볍고 정확. 없으면 list meta fallback.
  const unreadCount = useMemo(() => {
    const fromUnreadQuery = unreadQuery.data?.data?.unread_count;
    if (typeof fromUnreadQuery === 'number') return fromUnreadQuery;
    const fromListMeta = listQuery.data?.meta?.unread_count;
    if (typeof fromListMeta === 'number') return fromListMeta;
    return notifications.filter((n) => !n.is_read).length;
  }, [unreadQuery.data, listQuery.data, notifications]);

  const badgeText = unreadCount > 9 ? '9+' : String(unreadCount);

  // 외부 클릭 닫기
  useEffect(() => {
    if (!open) return;
    function handleClickOutside(e: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [open]);

  // ESC 닫기
  useEffect(() => {
    if (!open) return;
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
    }
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [open]);

  async function handleRowClick(n: Notification) {
    // 디버그: 클릭 → mutation 도달 여부 빠른 검증용
    console.debug('[NotificationBell] click', n.id, n.is_read);

    // 1) 안 읽음이면 mark_read 가 백엔드에 끝까지 도달하도록 await
    //    mutate() 는 fire-and-forget 이라 직후 router.push 가 fetch 를 abort 시킬 수 있음 → mutateAsync.
    if (!n.is_read) {
      try {
        await markRead.mutateAsync(n.id);
      } catch (e) {
        // mutation 실패해도 navigate 는 계속 (UX 우선)
        console.error('[NotificationBell] mark read failed:', e);
      }
    }

    // 2) link_url 있으면 그제서야 navigate
    if (n.link_url) {
      setOpen(false);
      router.push(n.link_url);
    }
  }

  async function handleMarkAll() {
    if (unreadCount === 0) return;
    try {
      await markAllRead.mutateAsync();
    } catch (e) {
      console.error('[NotificationBell] mark all read failed:', e);
    }
  }

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-label="알림"
        aria-expanded={open}
        className="relative flex h-9 w-9 items-center justify-center rounded-lg text-gray-400 hover:bg-gray-100 hover:text-gray-600"
      >
        <Bell className="h-5 w-5" />
        {unreadCount > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex min-w-[18px] items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-semibold leading-[18px] text-white">
            {badgeText}
          </span>
        )}
      </button>

      {open && (
        <div
          className="absolute right-0 top-12 z-50 flex w-[360px] max-w-[90vw] flex-col overflow-hidden rounded-xl border border-gray-100 bg-white shadow-lg"
          role="dialog"
          aria-label="알림 목록"
        >
          {/* 헤더 */}
          <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
            <p className="text-sm font-semibold text-gray-900">알림</p>
            <button
              type="button"
              onClick={handleMarkAll}
              disabled={unreadCount === 0 || markAllRead.isPending}
              className="text-xs font-medium text-primary-600 hover:text-primary-700 disabled:cursor-not-allowed disabled:text-gray-300"
            >
              모두 읽음
            </button>
          </div>

          {/* 본문 */}
          <div className="max-h-[480px] overflow-y-auto">
            {listQuery.isLoading ? (
              <div className="px-4 py-10 text-center text-sm text-gray-400">
                불러오는 중...
              </div>
            ) : listQuery.isError ? (
              <div className="px-4 py-10 text-center text-sm text-red-500">
                알림을 불러오지 못했습니다.
              </div>
            ) : notifications.length === 0 ? (
              <div className="px-4 py-12 text-center text-sm text-gray-400">
                새 알림이 없습니다
              </div>
            ) : (
              <ul className="divide-y divide-gray-100">
                {notifications.map((n) => (
                  <li key={n.id}>
                    <button
                      type="button"
                      onClick={() => handleRowClick(n)}
                      className="flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-gray-50"
                    >
                      {/* 좌측 안 읽음 점 + 타입 아이콘 */}
                      <div className="relative flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-primary-50 text-primary-600">
                        <NotificationIcon type={n.type} />
                        {!n.is_read && (
                          <span className="absolute -left-1 top-1/2 h-2 w-2 -translate-y-1/2 rounded-full bg-blue-500" />
                        )}
                      </div>

                      {/* 본문 */}
                      <div className="min-w-0 flex-1">
                        <div className="flex items-baseline justify-between gap-2">
                          <p
                            className={`truncate text-sm ${
                              n.is_read
                                ? 'text-gray-700'
                                : 'font-semibold text-gray-900'
                            }`}
                          >
                            {n.title}
                          </p>
                          <span className="flex-shrink-0 text-[11px] text-gray-400">
                            {formatRelativeKst(n.created_at)}
                          </span>
                        </div>
                        <p className="mt-0.5 line-clamp-2 text-xs text-gray-500">
                          {n.body}
                        </p>
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * 알림 타입별 아이콘.
 * - NEW_MESSAGE: 메시지 아이콘
 * - COUNTER_OFFER / OFFER_ACCEPTED / OFFER_REJECTED: 가격 협상 아이콘
 * - DELIVERY_DATE_*: 캘린더 아이콘
 * - ORDER_STATUS: 패키지(상태) 아이콘
 */
function NotificationIcon({ type }: { type: NotificationType }) {
  const iconClass = 'h-4 w-4';
  switch (type) {
    case 'NEW_MESSAGE':
      return <MessageCircle className={iconClass} />;
    case 'COUNTER_OFFER':
    case 'OFFER_ACCEPTED':
    case 'OFFER_REJECTED':
      return <CircleDollarSign className={iconClass} />;
    case 'DELIVERY_DATE_CHANGE':
    case 'DELIVERY_DATE_ACCEPTED':
    case 'DELIVERY_DATE_REJECTED':
      return <CalendarIcon className={iconClass} />;
    case 'ORDER_STATUS':
    default:
      return <Package className={iconClass} />;
  }
}
