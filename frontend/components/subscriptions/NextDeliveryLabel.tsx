'use client';

import Link from 'next/link';
import { AlertCircle } from 'lucide-react';
import { diffInDays, getTodayKstString } from '@/lib/date';
import { cn } from '@/lib/utils';

/**
 * 정기배송의 "다음 배송일" 을 D-day 카운트와 함께 표시하는 라벨.
 *
 * - prefix(기본 "다음 배송") + 'YYYY-MM-DD' + (D-N | D-Day | D+N 지남) 로 렌더링.
 * - D-Day 또는 이미 지난 경우 빨간색 강조 + AlertCircle 아이콘.
 * - calendarHref 가 있으면 <Link> 로, 없으면 <span> 으로 렌더링.
 *   부모(예: 정기배송 카드)가 행 펼침 onClick 을 가지고 있을 수 있으므로
 *   onClick 에 stopPropagation 을 적용하여 행 펼침과 분리한다.
 *
 * 오늘 날짜는 KST 기준 — getTodayKstString().
 * date prop 은 백엔드가 내려주는 'YYYY-MM-DD' 문자열 그대로 받는다.
 */
interface NextDeliveryLabelProps {
  /** 'YYYY-MM-DD' 문자열. null/undefined 면 "-" 만 표시. */
  date: string | null | undefined;
  /** 클릭 시 이동할 캘린더 URL — 보통 `/buyer/calendar?date=YYYY-MM-DD` 또는 `/seller/calendar?date=YYYY-MM-DD`. */
  calendarHref?: string;
  /** 라벨 앞 prefix. 기본 "다음 배송". */
  prefix?: string;
  /** 외부 wrapper 의 ARIA 라벨 (시멘틱 보강용). */
  ariaLabel?: string;
  /** 추가 클래스 (예: 부모 layout 의 text size 맞추기용). */
  className?: string;
}

export default function NextDeliveryLabel({
  date,
  calendarHref,
  prefix = '다음 배송',
  ariaLabel,
  className,
}: NextDeliveryLabelProps) {
  if (!date) {
    return (
      <span className={cn('text-xs text-gray-500', className)}>
        {prefix ? `${prefix}: -` : '-'}
      </span>
    );
  }

  const today = getTodayKstString();
  const diff = diffInDays(today, date);

  let dDay: string;
  let urgent = false;
  if (diff > 0) {
    dDay = `D-${diff}`;
  } else if (diff === 0) {
    dDay = 'D-Day';
    urgent = true;
  } else {
    dDay = `D+${Math.abs(diff)} 지남`;
    urgent = true;
  }

  const inner = (
    <span
      className={cn(
        'inline-flex items-center gap-1',
        urgent ? 'font-semibold text-red-600' : 'text-gray-500'
      )}
    >
      {urgent && <AlertCircle className="h-3 w-3 flex-shrink-0" aria-hidden="true" />}
      <span>
        {prefix ? `${prefix}: ` : ''}
        {date}{' '}
        <span className={cn(urgent ? 'text-red-600' : 'text-gray-400')}>({dDay})</span>
      </span>
    </span>
  );

  if (!calendarHref) {
    return <span className={cn('text-xs', className)} aria-label={ariaLabel}>{inner}</span>;
  }

  return (
    <Link
      href={calendarHref}
      // 부모 카드 onClick(행 펼침) 과 분리.
      onClick={(e) => e.stopPropagation()}
      aria-label={ariaLabel ?? `${prefix} ${date} 캘린더로 이동`}
      className={cn(
        'inline-flex items-center text-xs underline-offset-2 hover:underline',
        className
      )}
    >
      {inner}
    </Link>
  );
}
