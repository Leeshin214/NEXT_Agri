'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { cn } from '@/lib/utils';
import type { MenuItem } from '@/constants/menus';
import type { UserRole } from '@/types/user';

interface SidebarProps {
  menus: MenuItem[];
  currentPath: string;
  role?: UserRole;
}

/**
 * 사이드바 동작 정의 (호버 전용 — 핀/토글 개념 완전 제거)
 * - 작은/중간 화면 (lg 미만, <1024px):
 *   항상 w-16 collapsed 아이콘 사이드바가 absolute 로 표시 (디폴트).
 *   마우스 호버 시 w-56 으로 슬라이드 펼침 (overlay — 본문 안 밀림).
 *   마우스가 떠나면 즉시 w-16 으로 축소.
 *   본문은 좌측에 항상 w-16 자리표시 div가 차지하여 사이드바와 겹치지 않음.
 *   터치 디바이스(hover: none)는 끈적한 호버를 피하기 위해 호버 무시 → 항상 w-16 collapsed 유지.
 *   화살표/토글 버튼 없음 — 호버만으로 펼침/축소 결정.
 * - 큰 화면 (lg 이상, ≥1024px):
 *   인라인(relative)로 항상 w-56 펼쳐진 상태 고정. 본문 자연스럽게 밀림.
 */
export default function Sidebar({ menus, currentPath, role }: SidebarProps) {
  const [isHovered, setIsHovered] = useState(false);
  const [isLargeScreen, setIsLargeScreen] = useState(false);
  const [canHover, setCanHover] = useState(true);

  // lg(1024px) 이상 감지 — 항상 펼쳐진 상태로 강제
  useEffect(() => {
    const mq = window.matchMedia('(min-width: 1024px)');
    const update = () => setIsLargeScreen(mq.matches);
    update();
    mq.addEventListener('change', update);
    return () => mq.removeEventListener('change', update);
  }, []);

  // 마우스 호버가 가능한 디바이스인지 감지 (터치 디바이스는 끈적한 호버 회피)
  useEffect(() => {
    const mq = window.matchMedia('(hover: hover)');
    const update = () => setCanHover(mq.matches);
    update();
    mq.addEventListener('change', update);
    return () => mq.removeEventListener('change', update);
  }, []);

  // 효과적인 펼침 상태 계산
  // 큰 화면: 항상 true / 그 외: 호버 여부만으로 결정 (핀 개념 없음)
  const expanded = isLargeScreen || isHovered;

  // 호버 핸들러 — 호버 가능한 디바이스에서만 동작
  const handleMouseEnter = () => {
    if (canHover) setIsHovered(true);
  };
  const handleMouseLeave = () => setIsHovered(false);

  return (
    <>
      {/*
        lg 미만 자리표시 div
        - 사이드바를 absolute 로 띄우면 본문이 좌측으로 붙어버리므로,
          항상 w-16 자리를 인라인으로 차지시켜 본문 시작점을 고정.
        - 큰 화면(lg 이상)에서는 사이드바 자체가 인라인(relative)이므로 자리표시 불필요 → lg:hidden.
      */}
      <div className="block lg:hidden w-16 flex-shrink-0" aria-hidden="true" />

      <aside
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
        className={cn(
          'flex flex-col border-r border-gray-200 bg-white transition-all duration-200',
          // 작은/중간 화면 (lg 미만): absolute 오버레이로 본문 위에 떠있음, 호버로 너비 변화
          'absolute inset-y-0 left-0 z-40 shadow-sm',
          expanded ? 'w-56' : 'w-16',
          // 큰 화면 (lg 이상): 인라인(relative)로 자리 차지, 항상 w-56 펼쳐짐
          'lg:relative lg:w-56 lg:shadow-none lg:z-auto'
        )}
      >
        {/* 로고 */}
        <div className="flex h-16 items-center justify-center border-b border-gray-200 px-4">
          {expanded && (
            <Link href={role === 'SELLER' ? '/seller/dashboard' : '/buyer/dashboard'}>
              <span className="text-xl font-bold text-primary-700">fresh link</span>
            </Link>
          )}
        </div>

        {/* 역할 배지 */}
        {expanded && (
          <div className="border-b border-gray-200 px-4 py-3">
            <span
              className={cn(
                'inline-block rounded-full px-3 py-1 text-xs font-medium',
                role === 'SELLER'
                  ? 'bg-primary-100 text-primary-700'
                  : 'bg-blue-100 text-blue-700'
              )}
            >
              {role === 'SELLER' ? '판매자' : '구매자'}
            </span>
          </div>
        )}

        {/* 메뉴 */}
        <nav className="flex-1 overflow-y-auto px-2 py-3">
          {menus.map((menu) => {
            const isActive =
              currentPath === menu.href ||
              currentPath.startsWith(menu.href + '/');
            const Icon = menu.icon;

            return (
              <Link
                key={menu.href}
                href={menu.href}
                className={cn(
                  'mb-1 flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-primary-50 text-primary-700'
                    : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900',
                  !expanded && 'justify-center px-0'
                )}
                title={!expanded ? menu.label : undefined}
              >
                <Icon className="h-5 w-5 flex-shrink-0" />
                {expanded && <span>{menu.label}</span>}
              </Link>
            );
          })}
        </nav>
      </aside>
    </>
  );
}
