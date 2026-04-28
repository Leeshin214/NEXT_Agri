'use client';

import {
  createClient as createSupabaseClient,
  type SupabaseClient,
} from '@supabase/supabase-js';

const TAB_ID_KEY = 'agriflow-tab-id';

/**
 * 현재 탭의 고유 ID를 sessionStorage에서 가져오거나 새로 생성한다.
 * - 같은 탭은 새로고침해도 동일한 ID 유지 (sessionStorage 특성)
 * - 새 탭/창은 항상 새로운 ID 생성 → 탭 간 세션 격리
 *
 * SSR 환경(window 없음)에서는 'ssr' fallback.
 */
export function getTabId(): string {
  if (typeof window === 'undefined') return 'ssr';
  let id = sessionStorage.getItem(TAB_ID_KEY);
  if (!id) {
    id = crypto.randomUUID();
    sessionStorage.setItem(TAB_ID_KEY, id);
  }
  return id;
}

/**
 * 탭별로 격리된 Supabase 클라이언트.
 * - storageKey를 탭별 UUID로 분리 → 같은 도메인 내 탭이 서로 다른 계정으로 동시 로그인 가능
 * - storage = window.localStorage → 탭 닫기 후 재오픈 시에도 세션 유지(2일까지)
 *   주의: localStorage 자체는 탭 간 공유되지만, key가 다르므로 세션 격리됨
 * - persistSession + autoRefreshToken: Supabase 토큰 자동 갱신
 *
 * 모듈 레벨 캐시(_client)로 매 호출마다 같은 인스턴스를 반환한다.
 * 새 인스턴스를 만들면 onAuthStateChange 핸들러가 중복 등록되는 함정.
 */
let _client: SupabaseClient | null = null;

export function createClient(): SupabaseClient {
  // SSR fallback — Server Component에서 import해도 빌드 깨지지 않게.
  // 실제 인증 호출은 'use client' 컴포넌트에서만 일어남.
  if (typeof window === 'undefined') {
    return createSupabaseClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL!,
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
      {
        auth: {
          persistSession: false,
          autoRefreshToken: false,
        },
      }
    );
  }

  if (_client) return _client;

  const tabId = getTabId();
  _client = createSupabaseClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      auth: {
        storageKey: `agriflow-auth-${tabId}`,
        storage: window.localStorage,
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
      },
    }
  );

  return _client;
}
