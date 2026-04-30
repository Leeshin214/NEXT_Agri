'use client';

import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { createClient } from '@/lib/supabase/client';
import { useAuthStore } from '@/store/authStore';

/**
 * 본인 user_id 의 notifications INSERT / UPDATE 이벤트를 구독해
 * ['notifications'] 캐시(목록 + unread-count)를 invalidate 한다.
 *
 * 중복 구독 방지를 위해 앱 트리에서 **단 한 곳** 에서만 호출한다.
 * 현재 마운트 위치: NotificationBell (TopBar 안에서 렌더되는 단일 컴포넌트).
 *
 * 구현 노트:
 * - chat 훅과 동일한 createClient() 싱글턴 supabase 클라이언트 사용 (탭별 격리).
 * - filter `user_id=eq.${userId}` — Supabase Realtime 의 row level filter 로 본인 행만 수신.
 * - cleanup 에서 removeChannel 필수, 안 그러면 라우팅 시 채널 누수.
 * - INSERT 만이 아니라 UPDATE 도 listen — 같은 사용자가 다른 탭에서 mark_read 한 경우
 *   이 탭에도 즉시 반영되도록 (서버 측 is_read 컬럼 변경 감지).
 *   mark-read mutation 은 onSettled invalidate 를 안 하므로, 같은 탭의 다른 화면 갱신은
 *   이 UPDATE 이벤트가 보완 역할을 한다.
 */
export function useNotificationRealtime() {
  const queryClient = useQueryClient();
  const userId = useAuthStore((s) => s.user?.id);

  useEffect(() => {
    if (!userId) return;

    const supabase = createClient();
    const channel = supabase
      .channel(`notifications:${userId}`)
      .on(
        'postgres_changes',
        {
          event: 'INSERT',
          schema: 'public',
          table: 'notifications',
          filter: `user_id=eq.${userId}`,
        },
        () => {
          // 목록 + unread-count 동시 invalidate (둘 다 ['notifications', ...] 키)
          queryClient.invalidateQueries({ queryKey: ['notifications'] });
        }
      )
      .on(
        'postgres_changes',
        {
          event: 'UPDATE',
          schema: 'public',
          table: 'notifications',
          filter: `user_id=eq.${userId}`,
        },
        () => {
          queryClient.invalidateQueries({ queryKey: ['notifications'] });
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [userId, queryClient]);
}
