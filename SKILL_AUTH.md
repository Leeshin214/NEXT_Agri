# SKILL_AUTH.md — Auth & RBAC Agent

## 역할
Supabase Auth 기반의 인증 시스템과 역할 기반 접근 제어(RBAC)를 구현한다.

---

## 인증 플로우 (탭별 격리 + 클라이언트 가드 — 2026-04-27 재설계)

```
[회원가입]
1. 사용자 → 이메일/비밀번호 + 역할 선택 (SELLER/BUYER)
2. Supabase Auth signUp → 메타데이터(name, role, company_name) 전달
3. Supabase trigger handle_new_user → public.users 자동 생성
4. 세션 발급되면 setSession(user, expiresAt) 후 역할별 대시보드로

[로그인]
1. Supabase Auth signInWithPassword → 토큰 발급
   ↳ storageKey `agriflow-auth-{tabId}` 의 localStorage에 세션 저장 (탭별 격리)
2. /users/me 호출(또는 Supabase users 테이블 직접 조회) → 프로필 획득
3. setSession(profile, Date.now() + 2*24*60*60*1000) → store에 user + 만료시각 persist
   ↳ persist key는 `agriflow-auth-store-{tabId}` (탭별 격리)
4. 역할별 redirect (SELLER → /seller/dashboard, BUYER → /buyer/dashboard)

[보호 경로 진입 (모든 /seller/*, /buyer/*, /profile)]
- app/(dashboard)/layout.tsx 가 <AuthGuard>로 감싸 모든 진입점에 가드 적용
- AuthGuard mount 시:
  1. loginExpiresAt < Date.now() → signOut + /login
  2. supabase.auth.getSession() 없음 → /login
  3. store user 없음 → /users/me 호출 → setSession
  4. 역할 불일치 (SELLER가 /buyer/* 등) → 자기 역할 대시보드로 redirect
- pathname 변경 시마다 만료 재검증

[로그아웃]
- useAuth.signOut() 또는 onAuthStateChange의 SIGNED_OUT 이벤트
- supabase.auth.signOut() + queryClient.clear() + store.logout() + router.replace('/login')

[탭 격리 메커니즘]
- sessionStorage에 'agriflow-tab-id' (UUID) 저장 — 탭별 고유, 새로고침 시 유지
- Supabase storageKey, Zustand persist name 모두 이 tabId를 suffix로 사용
- 결과: 같은 노트북 같은 도메인에서도 탭마다 독립적인 로그인 세션 유지

[역할 확인]
- JWT payload에 role 없음 (Supabase 기본)
- FastAPI에서 users.role 컬럼으로 확인
- 클라이언트에서는 zustand authStore.user.role 으로 분기
- Next.js 미들웨어는 비활성화 (탭 격리 storage가 서버에 노출 안 됨)
```

---

## Supabase Auth 설정

### 1. Supabase 트리거 (신규 사용자 → users 테이블 동기화)
```sql
-- supabase/migrations/YYYYMMDDHHMMSS_auth_trigger.sql

CREATE OR REPLACE FUNCTION handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO public.users (supabase_uid, email, name, role, company_name)
  VALUES (
    NEW.id,
    NEW.email,
    COALESCE(NEW.raw_user_meta_data->>'name', ''),
    COALESCE(NEW.raw_user_meta_data->>'role', 'BUYER'),
    COALESCE(NEW.raw_user_meta_data->>'company_name', '')
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION handle_new_user();
```

### 2. 회원가입 시 메타데이터 전달
```typescript
// frontend에서 회원가입
const { error } = await supabase.auth.signUp({
  email,
  password,
  options: {
    data: {
      name: formData.name,
      role: formData.role,          // 'SELLER' or 'BUYER'
      company_name: formData.company_name,
    }
  }
});
```

---

## Next.js 미들웨어 (현재: 비활성화)

탭 격리 storage(sessionStorage tabId)는 서버에서 접근할 수 없으므로 미들웨어로는 세션 식별이 불가능하다. 따라서 **인증/역할 가드는 모두 클라이언트 사이드 `<AuthGuard>` 컴포넌트로 이전**되었다.

```typescript
// frontend/middleware.ts — 현재 모습
import { NextResponse } from 'next/server';

export function middleware() {
  return NextResponse.next();
}
export const config = { matcher: [] };
```

`lib/supabase/server.ts` 의 `createServerSupabaseClient` 도 더 이상 사용하지 않으며, 호출 시 명시적 에러를 던지도록 deprecated 처리되었다.

---

## Zustand Auth Store (탭별 격리 + 만료시각 + 하이드레이션 플래그 3중 안전장치)

```typescript
// frontend/store/authStore.ts
export const LOGIN_DURATION_MS = 2 * 24 * 60 * 60 * 1000; // 정확히 2일

interface AuthState {
  user: User | null;
  loginExpiresAt: number | null;          // 만료 epoch ms
  isLoading: boolean;
  isHydrated: boolean;                    // ← persist rehydration 완료 플래그
  setUser: (user: User | null) => void;
  setSession: (user: User, expiresAt: number) => void;  // 로그인 시 호출
  setLoading: (loading: boolean) => void;
  setHydrated: (hydrated: boolean) => void;
  logout: () => void;                     // user + loginExpiresAt 모두 null로
}

// persist name을 tabId suffix로 분리 → 탭마다 독립된 store
const persistName = `agriflow-auth-store-${getTabId()}`;
// partialize: user + loginExpiresAt 둘 다 persist 대상
persist(..., {
  name: persistName,
  storage: createJSONStorage(() => window.localStorage),
  partialize: (s) => ({ user: s.user, loginExpiresAt: s.loginExpiresAt }),
  // ⚠️ persist 데이터가 localStorage에 이미 있을 때만 호출됨 (첫 로그인엔 호출 X)
  onRehydrateStorage: () => () => {
    useAuthStore.setState({ isHydrated: true });
  },
});

// ─── 모듈 레벨 hydration 가드 (3중 안전장치) — 첫 로그인 무한 로딩 방지 ───
if (typeof window !== 'undefined') {
  if (useAuthStore.persist.hasHydrated()) {
    useAuthStore.setState({ isHydrated: true });
  } else {
    useAuthStore.persist.onFinishHydration(() => {
      useAuthStore.setState({ isHydrated: true });
    });
    // 마지막 안전망: 빈 localStorage(첫 로그인) 케이스 등에서
    // onRehydrateStorage/onFinishHydration 둘 다 호출 안 될 때 200ms 후 강제 true
    setTimeout(() => {
      if (!useAuthStore.getState().isHydrated) {
        useAuthStore.setState({ isHydrated: true });
      }
    }, 200);
  }
}
```

`getTabId()` 는 `sessionStorage['agriflow-tab-id']` 에 UUID 저장. Supabase 클라이언트와 동일한 키를 공유하여 탭 단위 격리.

---

## Auth 훅 (단순화 — store 노출 + signOut만)

세션 동기화/만료 검증/역할 라우팅은 모두 `<AuthGuard>` 가 처리한다. `useAuth` 는 TopBar 등에서 user/signOut만 필요한 곳을 위한 얇은 wrapper.

```typescript
// frontend/hooks/useAuth.ts
export function useAuth() {
  const { user, logout } = useAuthStore();
  const router = useRouter();
  const queryClient = useQueryClient();

  const signOut = async () => {
    const supabase = createClient();
    await supabase.auth.signOut();
    queryClient.clear();           // 캐시 누락 방지 (검증됨)
    logout();                       // user + loginExpiresAt 둘 다 null
    router.replace('/login');
  };

  return { user, signOut };
}
```

## AuthGuard 컴포넌트

```typescript
// frontend/components/common/AuthGuard.tsx
// (dashboard) layout에서 children을 감싸는 클라이언트 가드.
//
// 책임:
// 1. mount 시 loginExpiresAt 만료 검사 → 만료면 signOut + /login
// 2. supabase.auth.getSession() 없으면 /login
// 3. store.user 없으면 /users/me로 프로필 조회 후 setSession(user, Date.now()+2일)
// 4. 역할 불일치 (SELLER/buyer 또는 BUYER/seller) 시 자기 역할 대시보드로 redirect
// 5. onAuthStateChange 구독 — SIGNED_OUT 발생 시 자동 로그아웃 처리
//
// 준비될 때까지 (!isReady) "불러오는 중..." 표시. 라우팅 중 데이터 노출 방지.

// frontend/app/(dashboard)/layout.tsx
return (
  <AuthGuard>
    <AppLayout>{children}</AppLayout>
  </AuthGuard>
);
```

---

## FastAPI JWT 검증

```python
# app/core/security.py
import json
from typing import Any

import httpx
import jwt
from fastapi import HTTPException, status
from jwt.algorithms import ECAlgorithm

from app.core.config import settings

_jwks_cache: dict | None = None


async def _get_supabase_public_key(kid: str | None) -> Any:
    global _jwks_cache
    if _jwks_cache is None:
        jwks_url = f"{settings.SUPABASE_URL}/auth/v1/.well-known/jwks.json"
        async with httpx.AsyncClient() as client:
            resp = await client.get(jwks_url, timeout=5.0)
            resp.raise_for_status()
            _jwks_cache = resp.json()

    keys = _jwks_cache.get("keys", [])
    key_data = next((k for k in keys if k.get("kid") == kid), None)
    if key_data is None and keys:
        key_data = keys[0]
    if key_data is None:
        raise HTTPException(status_code=401, detail="JWKS: no matching key")

    return ECAlgorithm.from_jwk(json.dumps(key_data))


async def verify_supabase_jwt(token: str) -> dict:
    """Supabase JWT 토큰 검증 및 payload 반환"""
    try:
        header = jwt.get_unverified_header(token)
        alg = header.get("alg", "")

        if alg == "ES256":
            public_key = await _get_supabase_public_key(header.get("kid"))
            payload = jwt.decode(
                token,
                public_key,
                algorithms=["ES256"],
                audience="authenticated",
                options={"verify_exp": True},
            )
        else:
            payload = jwt.decode(
                token,
                settings.SUPABASE_JWT_SECRET,
                algorithms=["HS256", "HS512"],
                audience="authenticated",
                options={"verify_exp": True},
            )

        return payload

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except HTTPException:
        raise
    except jwt.InvalidTokenError as e:
        print(f"[AUTH] JWT 검증 실패: {str(e)}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {str(e)}")
```

> `verify_supabase_jwt`는 `async def`이므로 `dependencies.py`의 `get_current_user`에서 반드시 `await`로 호출해야 한다.

---

## 역할별 API 접근 제어

```python
# app/dependencies.py

# 판매자만 접근 가능
require_seller = require_role("SELLER")
# 구매자만 접근 가능
require_buyer = require_role("BUYER")

# 사용 예시
@router.post("/products")
async def create_product(
    data: ProductCreate,
    current_user: User = Depends(require_seller)  # 판매자만
):
    ...

@router.post("/orders")
async def create_order(
    data: OrderCreate,
    current_user: User = Depends(require_buyer)  # 구매자만
):
    ...
```

---

## 작업 체크리스트

- [ ] Supabase Auth trigger SQL 작성 (users 테이블 동기화)
- [ ] Next.js middleware.ts (라우트 보호 + 역할 기반 리다이렉트)
- [ ] Supabase client/server 설정 파일
- [ ] Zustand auth store
- [ ] useAuth 훅
- [ ] 로그인 페이지 UI
- [ ] 회원가입 페이지 UI (역할 선택 포함)
- [ ] FastAPI JWT 검증 함수
- [ ] require_role 의존성 함수
- [ ] 세션 만료 처리 (자동 갱신 or 로그인 페이지 리다이렉트)

---

## 실전 발견 사항

### 검증된 패턴

#### 탭별 격리 Supabase 클라이언트 (검증됨, 2026-04-27)

같은 노트북 같은 도메인에서 탭 2개에 서로 다른 계정으로 동시 로그인하기 위해 Supabase 클라이언트를 탭 단위로 격리한다.

핵심 아이디어:
- `sessionStorage['agriflow-tab-id']`에 UUID 저장 → 탭마다 고유, 새로고침 시 유지, 새 탭은 새 UUID
- Supabase `storageKey: 'agriflow-auth-{tabId}'` + `storage: window.localStorage` → 탭별 다른 key, 탭 닫고 다시 열어도 2일까지 세션 유지
- `@supabase/ssr` 의 `createBrowserClient` (쿠키 기반) 대신 `@supabase/supabase-js` 의 `createClient` 사용
- 모듈 레벨 `_client` 캐시 필수 — 매번 새로 만들면 `onAuthStateChange` 핸들러가 중복 등록됨

```typescript
// frontend/lib/supabase/client.ts
let _client: SupabaseClient | null = null;

export function createClient(): SupabaseClient {
  if (typeof window === 'undefined') {
    return createSupabaseClient(URL!, KEY!, {
      auth: { persistSession: false, autoRefreshToken: false }
    });
  }
  if (_client) return _client;
  const tabId = getTabId();
  _client = createSupabaseClient(URL!, KEY!, {
    auth: {
      storageKey: `agriflow-auth-${tabId}`,
      storage: window.localStorage,
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true,
    },
  });
  return _client;
}
```

#### Zustand persist도 탭 단위로 분리 (검증됨)

authStore의 persist `name`도 동일한 tabId를 suffix로 사용해야 한다. Supabase 세션은 탭별로 격리됐는데 zustand store는 공유되면 마지막 로그인이 다른 탭의 store를 덮어쓰는 버그 발생.

```typescript
// frontend/store/authStore.ts
const persistName = typeof window !== 'undefined'
  ? `agriflow-auth-store-${getTabId()}`
  : 'agriflow-auth-store-ssr';

persist(..., { name: persistName, storage: createJSONStorage(() => window.localStorage), ... })
```

#### 2일 만료 정책 — loginExpiresAt 패턴 (검증됨)

Supabase 자체 토큰 만료(보통 1시간)는 자동 갱신되어 사실상 무한 유지된다. 따라서 별도의 "로그인 유지 기간" 개념을 zustand store에 구현해야 정확히 2일 정책이 적용된다.

- 로그인 시: `setSession(user, Date.now() + 2*24*60*60*1000)`
- AuthGuard mount 시 + pathname 변경 시: `loginExpiresAt < Date.now()` → 강제 signOut
- partialize에 `loginExpiresAt` 포함 → 탭 닫았다 다시 열어도 만료 시각 유지

#### 미들웨어 비활성화 + 클라이언트 가드로 통합 (검증됨)

탭 격리 storage(sessionStorage tabId)는 서버에 노출되지 않으므로 미들웨어로는 세션 식별이 불가능하다.
- `frontend/middleware.ts` → `matcher: []` 로 비활성화
- `app/(dashboard)/layout.tsx` 가 `<AuthGuard>` 로 children을 감싸 모든 보호 경로에 가드 적용
- 역할별 라우팅(`SELLER` ↔ `BUYER` 경로 차단)도 AuthGuard 안에서 처리
- 루트 `/` → `app/page.tsx` 도 `'use client'` 로 변경하여 store 기반 분기

### 주의사항 & 함정

- **persist `onRehydrateStorage` 는 빈 localStorage 에서 호출 안 됨 (확정 함정, 2026-05-04)**: Zustand persist 의 `onRehydrateStorage` 콜백은 localStorage 에 persist 데이터가 존재할 때만 호출된다. 첫 로그인처럼 storage 가 비어 있으면 콜백이 영원히 호출되지 않아 `isHydrated` 가 `false` 로 고정되고, AuthGuard 의 `if (!isHydrated) return` 에서 영원히 막혀 "불러오는 중..." 화면이 무한 로딩된다. 해결: 모듈 레벨에서 `useAuthStore.persist.hasHydrated()` 체크 + `onFinishHydration` 등록 + 200ms `setTimeout` fallback 의 3중 안전장치를 추가한다 (위 store 코드 참고). 이 보강을 빼면 새로운 사용자/계정 추가 시 즉시 무한 로딩으로 막힌다.

- **로그인 직후 setUser 즉시 호출 필수 (함정)**: `login/page.tsx`에서 로그인 성공 후 `router.push()`만 하면 안 된다. redirect 후 `useAuth` 훅이 TopBar에서 비동기로 프로필을 가져오는 동안 Zustand persist에서 복원된 stale 데이터나 null이 사용된다. 특히 채팅 페이지에서 `msg.sender_id === user?.id` 비교 시 `user.id`가 `''`이면 모든 메시지가 상대방 메시지로 보이는 버그가 발생한다. 반드시 로그인 시 `select('*')`로 전체 프로필을 가져와 `useAuthStore.getState().setUser(profile)`로 즉시 저장한다.
  ```typescript
  // login/page.tsx — 올바른 패턴
  const { data: profile } = await supabase
    .from('users')
    .select('*')           // role만 가져오면 안 됨
    .eq('supabase_uid', user.id)
    .single();

  if (profile) {
    useAuthStore.getState().setUser(profile);  // redirect 전에 즉시 저장
  }
  router.push(redirectPath);
  ```

- **useAuth — users 테이블 null 폴백 필수**: Supabase Auth trigger가 아직 실행되지 않았거나 실패한 경우 `users` 테이블에 레코드가 없을 수 있다. `setUser(profile)` 전에 `if (profile)` 분기를 두고, null이면 `data.user.user_metadata`(회원가입 시 전달한 name, role, company_name)로 폴백 User 객체를 구성해 `setUser`해야 한다. 그렇지 않으면 store가 null이 돼 마이페이지/TopBar 등 모든 user 의존 UI가 깨진다.

- **Supabase JWT secret — base64 decode 금지**: Supabase GoTrue는 `jwt.SignedString([]byte(jwtSecret))`로 서명한다. 즉 secret 문자열을 UTF-8 bytes로 그대로 사용한다. PyJWT도 string 키를 UTF-8로 변환하므로 둘이 일치한다. `base64.b64decode(settings.SUPABASE_JWT_SECRET)`를 하면 secret이 달라져서 서명 검증이 항상 실패한다. `jwt.decode(token, settings.SUPABASE_JWT_SECRET, ...)` 형태로 string을 그대로 전달해야 한다.

- **algorithms 리스트에 HS512 포함**: Supabase는 HS256 외 HS512도 사용할 수 있다. `algorithms=["HS256", "HS512"]`로 설정해야 "The specified alg value is not allowed" 에러를 방지할 수 있다.

- **ES256 토큰 — JWKS 공개 키 검증 (확정)**: Supabase는 ES256(타원 곡선 비대칭) 알고리즘을 사용할 수 있으며, 이 경우 대칭 키(`SUPABASE_JWT_SECRET`)로는 검증이 불가하다. `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`에서 공개 키를 받아 `ECAlgorithm.from_jwk()`로 변환한 뒤 `algorithms=["ES256"]`으로 검증해야 한다. `pyjwt[crypto]` extras가 필수이며, JWKS는 모듈 레벨 변수에 캐시해 반복 HTTP 요청을 방지한다. `verify_supabase_jwt`는 `async def`로 선언하고 호출 측에서 `await`해야 한다.
