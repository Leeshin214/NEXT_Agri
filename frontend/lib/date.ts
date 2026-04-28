/**
 * 캘린더 날짜 포맷 유틸 — 'YYYY-MM-DD' 문자열 기반.
 * Date 객체로 변환하더라도 요일 계산 외에는 사용하지 않으므로 timezone 영향 없음.
 */

const KOREAN_WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토'] as const;

/**
 * 'YYYY-MM-DD' → 'YYYY년 M월 D일 (요일)'
 * 입력이 잘못되면 원본 문자열을 그대로 반환한다.
 */
export function formatKoreanDateWithWeekday(dateStr: string): string {
  const [y, m, d] = dateStr.split('-');
  if (!y || !m || !d) return dateStr;
  const yearNum = Number(y);
  const monthNum = Number(m);
  const dayNum = Number(d);
  if (Number.isNaN(yearNum) || Number.isNaN(monthNum) || Number.isNaN(dayNum)) {
    return dateStr;
  }
  const weekdayIdx = new Date(yearNum, monthNum - 1, dayNum).getDay();
  const weekday = KOREAN_WEEKDAYS[weekdayIdx] ?? '';
  return `${yearNum}년 ${monthNum}월 ${dayNum}일 (${weekday})`;
}
