# SKILL_AUTH.md — Auth & RBAC Agent

## 역할
Supabase Auth 기반의 인증 시스템과 역할 기반 접근 제어(RBAC)를 구현한다.

---

## 인증 플로우

```
[회원가입]
1. 사용자 → 이메일/비밀번호 + 역할 선택 (SELLER/BUYER)
2. Supabase Auth → 이메일 인증 발송
3. 인증 완료 → Supabase trigger가 users 테이블에 프로필 자동 생성

[로그인]
1. Supabase Auth → JWT access_token 발급
2. Frontend → JWT를 localStorage or httpOnly cookie에 저장
3. API 요청 시 Authorization: Bearer {token} 헤더 포함
4. FastAPI → JWT 검증 → users 테이블에서 프로필 조회

[역할 확인]
- JWT payload에 role 없음 (Supabase 기본)
- FastAPI에서 users.role 컬럼으로 확인
- Next.js 미들웨어에서 cookie의 role 값으로 라우팅 제어
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

## Next.js 미들웨어 (라우트 보호)

```typescript
// src/middleware.ts
import { createServerClient } from '@supabase/ssr';
import { NextResponse, type NextRequest } from 'next/server';

export async function middleware(request: NextRequest) {
  let response = NextResponse.next({ request });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() { return request.cookies.getAll() },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value, options }) =>
            response.cookies.set(name, value, options)
          );
        },
      },
    }
  );

  const { data: { user } } = await supabase.auth.getUser();

  // 미로그인 → 로그인 페이지로
  if (!user && request.nextUrl.pathname.startsWith('/(dashboard)')) {
    return NextResponse.redirect(new URL('/login', request.url));
  }

  // 로그인 상태에서 역할 기반 라우팅
  if (user) {
    const { data: profile } = await supabase
      .from('users')
      .select('role')
      .eq('supabase_uid', user.id)
      .single();

    const role = profile?.role;
    const path = request.nextUrl.pathname;

    // 판매자가 구매자 경로 접근 시 차단
    if (role === 'SELLER' && path.startsWith('/buyer')) {
      return NextResponse.redirect(new URL('/seller/dashboard', request.url));
    }
    if (role === 'BUYER' && path.startsWith('/seller')) {
      return NextResponse.redirect(new URL('/buyer/dashboard', request.url));
    }

    // 루트 접근 시 역할별 대시보드로
    if (path === '/') {
      return NextResponse.redirect(
        new URL(role === 'SELLER' ? '/seller/dashboard' : '/buyer/dashboard', request.url)
      );
    }
  }

  return response;
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico|login|register).*)'],
};
```

---

## Zustand Auth Store

```typescript
// src/store/authStore.ts
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { User } from '@/types/user';

interface AuthState {
  user: User | null;
  isLoading: boolean;
  setUser: (user: User | null) => void;
  setLoading: (loading: boolean) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      isLoading: true,
      setUser: (user) => set({ user, isLoading: false }),
      setLoading: (isLoading) => set({ isLoading }),
      logout: () => set({ user: null }),
    }),
    { name: 'auth-storage', partialize: (state) => ({ user: state.user }) }
  )
);
```

---

## Auth 훅

```typescript
// src/hooks/useAuth.ts
'use client';
import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { createClient } from '@/lib/supabase/client';
import { useAuthStore } from '@/store/authStore';

export function useAuth() {
  const { user, setUser, setLoading, logout } = useAuthStore();
  const router = useRouter();
  const supabase = createClient();

  useEffect(() => {
    // 세션 동기화
    supabase.auth.getUser().then(async ({ data }) => {
      if (data.user) {
        const { data: profile } = await supabase
          .from('users')
          .select('*')
          .eq('supabase_uid', data.user.id)
          .single();

        if (profile) {
          setUser(profile);
        } else {
          // users 테이블에 레코드가 없을 때 Auth 메타데이터로 폴백
          setUser({
            id: '',
            supabase_uid: data.user.id,
            email: data.user.email ?? '',
            name: (data.user.user_metadata?.name as string) ?? '',
            role: (data.user.user_metadata?.role as 'SELLER' | 'BUYER' | 'ADMIN') ?? 'BUYER',
            company_name: (data.user.user_metadata?.company_name as string) ?? null,
            phone: null,
            profile_image: null,
            is_active: true,
            created_at: data.user.created_at ?? '',
            updated_at: data.user.created_at ?? '',
            deleted_at: null,
          });
        }
      } else {
        setUser(null);
      }
    });

    // 인증 상태 변화 감지
    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      async (event, session) => {
        if (event === 'SIGNED_OUT') {
          logout();
          router.push('/login');
        }
      }
    );

    return () => subscription.unsubscribe();
  }, []);

  const signOut = async () => {
    await supabase.auth.signOut();
    logout();
    router.push('/login');
  };

  return { user, signOut };
}
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

### 주의사항 & 함정

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
