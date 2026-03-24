import { createServerClient } from '@supabase/ssr';
import type { CookieOptions } from '@supabase/ssr';
import { NextResponse, type NextRequest } from 'next/server';

export async function middleware(request: NextRequest) {
  let response = NextResponse.next({ request });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet: { name: string; value: string; options: CookieOptions }[]) {
          cookiesToSet.forEach(({ name, value, options }) =>
            response.cookies.set(name, value, options)
          );
        },
      },
    }
  );

  const {
    data: { user },
  } = await supabase.auth.getUser();

  const path = request.nextUrl.pathname;

  // 미로그인 → 보호된 경로 접근 시 로그인으로 리다이렉트
  if (!user && !path.startsWith('/login') && !path.startsWith('/register')) {
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

    // 판매자가 구매자 경로 접근 시 차단
    if (role === 'SELLER' && path.startsWith('/buyer')) {
      return NextResponse.redirect(
        new URL('/seller/dashboard', request.url)
      );
    }
    if (role === 'BUYER' && path.startsWith('/seller')) {
      return NextResponse.redirect(
        new URL('/buyer/dashboard', request.url)
      );
    }

    // 루트 접근 시 역할별 대시보드로
    if (path === '/') {
      return NextResponse.redirect(
        new URL(
          role === 'SELLER' ? '/seller/dashboard' : '/buyer/dashboard',
          request.url
        )
      );
    }

    // 로그인/회원가입 페이지에 접근 시 대시보드로
    if (path.startsWith('/login') || path.startsWith('/register')) {
      return NextResponse.redirect(
        new URL(
          role === 'SELLER' ? '/seller/dashboard' : '/buyer/dashboard',
          request.url
        )
      );
    }
  }

  return response;
}

export const config = {
  matcher: [
    '/((?!_next/static|_next/image|favicon.ico|api).*)',
  ],
};
