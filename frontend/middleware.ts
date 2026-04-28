import { NextResponse } from 'next/server';

/**
 * 인증 검사를 클라이언트로 이전하면서 미들웨어는 비활성화 상태로 둔다.
 * - 탭별 격리 storage(sessionStorage tabId 기반)는 서버에서 접근할 수 없어 미들웨어에서 세션 식별 불가
 * - 미보호 경로 통과만 담당. 인증/역할 체크는 components/common/AuthGuard.tsx에서 수행
 */
export function middleware() {
  return NextResponse.next();
}

export const config = {
  matcher: [],
};
