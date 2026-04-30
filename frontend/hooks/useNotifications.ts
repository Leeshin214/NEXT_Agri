'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';
import type {
  MarkAllReadData,
  Notification,
  NotificationListMeta,
  SuccessResponse,
  UnreadCountData,
} from '@/types';

interface UseNotificationsOptions {
  limit?: number;
  onlyUnread?: boolean;
}

/**
 * 알림 목록 + meta(unread_count, total).
 *
 * - 쿼리 키: ['notifications', { limit, onlyUnread }]
 * - staleTime 30초 — Realtime INSERT 시 useNotificationRealtime 이 invalidate 하므로 길게 OK.
 * - 로그인 안 됐으면 disabled.
 */
export function useNotifications(opts?: UseNotificationsOptions) {
  const limit = opts?.limit ?? 30;
  const onlyUnread = opts?.onlyUnread ?? false;
  const userId = useAuthStore((s) => s.user?.id);

  return useQuery<SuccessResponse<Notification[]> & { meta?: NotificationListMeta }>({
    queryKey: ['notifications', { limit, onlyUnread }],
    queryFn: () =>
      api.get<SuccessResponse<Notification[]> & { meta?: NotificationListMeta }>(
        '/notifications',
        { limit, only_unread: onlyUnread }
      ),
    enabled: !!userId,
    staleTime: 30_000,
  });
}

/**
 * 미읽음 카운트만 조회 (가벼운 폴링용 fallback).
 *
 * - Realtime 이 끊겼을 경우 대비해 60초 polling 으로 동기화.
 * - 종 아이콘 뱃지가 항상 이 훅을 구독하므로 staleTime 30초.
 * - refetchOnMount: false — mutation 직후 mount 변화로 refetch 가 일어나
 *   optimistic 으로 0 만든 cache 를 옛 server 응답으로 덮어쓰는 race 를 방지.
 *   (Realtime UPDATE / 60초 polling 으로 결국 동기화됨)
 */
export function useUnreadCount() {
  const userId = useAuthStore((s) => s.user?.id);

  return useQuery<SuccessResponse<UnreadCountData>>({
    queryKey: ['notifications', 'unread-count'],
    queryFn: () =>
      api.get<SuccessResponse<UnreadCountData>>('/notifications/unread-count'),
    enabled: !!userId,
    staleTime: 30_000,
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
    refetchOnMount: false,
  });
}

/**
 * 단건 읽음 처리. Optimistic update 로 종 뱃지가 즉시 줄어들도록 한다.
 *
 * 중요한 race 회피:
 * - onMutate 에서 cancelQueries 호출 안 함. 60초 polling 의 in-flight 요청을 cancel
 *   하다가 mutationFn 시작이 미뤄지면 router.push 가 fetch 를 abort 시킨다.
 * - onSuccess 에서 server 응답으로 cache 직접 setQueryData → invalidate refetch 의존 X.
 * - onSettled 에서 invalidate 안 함. 그러면 직후 polling refetch 가 옛 server 응답으로
 *   optimistic cache 를 덮어쓸 위험 차단. (다음 60초 polling / Realtime UPDATE 로 자연 동기화)
 */
export function useMarkNotificationRead() {
  const queryClient = useQueryClient();

  return useMutation<
    SuccessResponse<Notification>,
    Error,
    string,
    {
      previousLists: Array<[readonly unknown[], unknown]>;
      previousCount: SuccessResponse<UnreadCountData> | undefined;
    }
  >({
    mutationFn: (notificationId: string) =>
      api.post<SuccessResponse<Notification>>(
        `/notifications/${notificationId}/read`
      ),
    onMutate: (notificationId) => {
      // cancelQueries 호출 제거 — polling refetch 가 cancel 에 hang 되는 것을 차단

      // 모든 ['notifications', ...] 목록 캐시 스냅샷 (limit/onlyUnread 변형 포함)
      const previousLists = queryClient.getQueriesData<
        SuccessResponse<Notification[]> & { meta?: NotificationListMeta }
      >({ queryKey: ['notifications'] });

      // 뱃지 unread-count 별도 스냅샷
      const previousCount = queryClient.getQueryData<
        SuccessResponse<UnreadCountData>
      >(['notifications', 'unread-count']);

      // 목록 캐시 — 해당 알림 is_read=true + meta.unread_count 감소
      previousLists.forEach(([key, value]) => {
        if (!value || !('data' in (value as object))) return;
        const cast = value as SuccessResponse<Notification[]> & {
          meta?: NotificationListMeta;
        };
        // unread-count 단일 객체 캐시는 data 가 배열이 아니므로 건너뜀
        if (!Array.isArray(cast.data)) return;
        const target = cast.data.find((n) => n.id === notificationId);
        if (!target || target.is_read) return;
        const nextData = cast.data.map((n) =>
          n.id === notificationId
            ? { ...n, is_read: true, read_at: new Date().toISOString() }
            : n
        );
        const nextMeta = cast.meta
          ? {
              ...cast.meta,
              unread_count: Math.max(0, cast.meta.unread_count - 1),
            }
          : cast.meta;
        queryClient.setQueryData(key, { ...cast, data: nextData, meta: nextMeta });
      });

      // unread-count 캐시
      if (previousCount?.data) {
        queryClient.setQueryData<SuccessResponse<UnreadCountData>>(
          ['notifications', 'unread-count'],
          {
            ...previousCount,
            data: {
              unread_count: Math.max(0, previousCount.data.unread_count - 1),
            },
          }
        );
      }

      return { previousLists, previousCount };
    },
    onSuccess: (response, notificationId) => {
      // 서버 진실로 cache 직접 업데이트 — invalidate refetch race 의존 X
      const updated = response.data;
      queryClient.setQueriesData<
        SuccessResponse<Notification[]> & { meta?: NotificationListMeta }
      >({ queryKey: ['notifications'] }, (old) => {
        if (!old || !('data' in (old as object))) return old;
        const cast = old as SuccessResponse<Notification[]> & {
          meta?: NotificationListMeta;
        };
        // unread-count 캐시 (data 가 배열 아님) 는 건너뜀
        if (!Array.isArray(cast.data)) return old;
        return {
          ...cast,
          data: cast.data.map((n) => (n.id === notificationId ? updated : n)),
        };
      });
      // unread-count 는 onMutate 에서 -1 해둔 값 그대로 신뢰 (server 와 일치)
    },
    onError: (_err, _id, ctx) => {
      ctx?.previousLists.forEach(([key, value]) => {
        queryClient.setQueryData(key, value);
      });
      if (ctx?.previousCount !== undefined) {
        queryClient.setQueryData(
          ['notifications', 'unread-count'],
          ctx.previousCount
        );
      }
    },
    // onSettled invalidate 제거 — refetch race 방지 (Realtime UPDATE / polling 으로 동기화됨)
  });
}

/**
 * 본인 미읽음 알림 전체 읽음 처리.
 * Optimistic update 로 뱃지를 즉시 0 으로 만든다.
 *
 * race 회피 정책은 useMarkNotificationRead 와 동일:
 * - onMutate 에서 cancelQueries 호출 안 함 (polling cancel hang 방지)
 * - onSuccess 에서 cache 를 명시적으로 일괄 read 처리 (server 응답 신뢰)
 * - onSettled 에서 invalidate 안 함 (옛 응답으로 덮어쓰는 race 방지)
 */
export function useMarkAllNotificationsRead() {
  const queryClient = useQueryClient();

  return useMutation<
    SuccessResponse<MarkAllReadData>,
    Error,
    void,
    {
      previousLists: Array<[readonly unknown[], unknown]>;
      previousCount: SuccessResponse<UnreadCountData> | undefined;
    }
  >({
    mutationFn: () =>
      api.post<SuccessResponse<MarkAllReadData>>('/notifications/read-all'),
    onMutate: () => {
      // cancelQueries 제거 — polling refetch hang 방지

      const previousLists = queryClient.getQueriesData<
        SuccessResponse<Notification[]> & { meta?: NotificationListMeta }
      >({ queryKey: ['notifications'] });

      const previousCount = queryClient.getQueryData<
        SuccessResponse<UnreadCountData>
      >(['notifications', 'unread-count']);

      const nowIso = new Date().toISOString();
      previousLists.forEach(([key, value]) => {
        if (!value || !('data' in (value as object))) return;
        const cast = value as SuccessResponse<Notification[]> & {
          meta?: NotificationListMeta;
        };
        // unread-count 단일 객체 캐시는 data 가 배열이 아니므로 건너뜀
        if (!Array.isArray(cast.data)) return;
        const nextData = cast.data.map((n) =>
          n.is_read ? n : { ...n, is_read: true, read_at: nowIso }
        );
        const nextMeta = cast.meta
          ? { ...cast.meta, unread_count: 0 }
          : cast.meta;
        queryClient.setQueryData(key, { ...cast, data: nextData, meta: nextMeta });
      });

      if (previousCount?.data) {
        queryClient.setQueryData<SuccessResponse<UnreadCountData>>(
          ['notifications', 'unread-count'],
          { ...previousCount, data: { unread_count: 0 } }
        );
      }

      return { previousLists, previousCount };
    },
    onSuccess: () => {
      // server 의 read-all 은 응답에 updated 카운트만 포함 → cache 의 모든 항목을 일괄 read 처리
      const nowIso = new Date().toISOString();
      queryClient.setQueriesData<
        SuccessResponse<Notification[]> & { meta?: NotificationListMeta }
      >({ queryKey: ['notifications'] }, (old) => {
        if (!old || !('data' in (old as object))) return old;
        const cast = old as SuccessResponse<Notification[]> & {
          meta?: NotificationListMeta;
        };
        // unread-count 캐시 (data 가 배열 아님) 별도 처리
        if (!Array.isArray(cast.data)) {
          // unread-count 단건 객체 캐시 → 0 으로 강제
          const single = cast as unknown as SuccessResponse<UnreadCountData>;
          if (single.data && typeof single.data.unread_count === 'number') {
            return {
              ...single,
              data: { unread_count: 0 },
            } as unknown as SuccessResponse<Notification[]> & {
              meta?: NotificationListMeta;
            };
          }
          return old;
        }
        return {
          ...cast,
          data: cast.data.map((n) =>
            n.is_read ? n : { ...n, is_read: true, read_at: nowIso }
          ),
          meta: cast.meta ? { ...cast.meta, unread_count: 0 } : cast.meta,
        };
      });
    },
    onError: (_err, _vars, ctx) => {
      ctx?.previousLists.forEach(([key, value]) => {
        queryClient.setQueryData(key, value);
      });
      if (ctx?.previousCount !== undefined) {
        queryClient.setQueryData(
          ['notifications', 'unread-count'],
          ctx.previousCount
        );
      }
    },
    // onSettled invalidate 제거 — refetch race 방지
  });
}
