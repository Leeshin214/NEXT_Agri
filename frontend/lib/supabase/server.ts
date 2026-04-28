/**
 * @deprecated
 * 인증이 클라이언트 사이드(탭별 격리 storage)로 이전되어 더 이상 사용하지 않는다.
 * Server Component에서 인증된 데이터 접근이 필요하면 백엔드 API(`/api/v1/...`)를 호출하거나
 * 페이지를 'use client' 컴포넌트로 전환하라.
 *
 * 호환성을 위해 export는 남겨두지만 호출 시 명시적으로 에러를 던진다.
 */
export function createServerSupabaseClient(): never {
  throw new Error(
    '[supabase/server] createServerSupabaseClient는 더 이상 지원되지 않습니다. ' +
      '클라이언트 사이드 createClient()를 사용하거나 백엔드 API를 호출하세요.'
  );
}
