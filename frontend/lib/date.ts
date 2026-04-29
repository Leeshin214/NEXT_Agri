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

/**
 * KST(UTC+9) 기준 오늘 날짜를 'YYYY-MM-DD' 문자열로 반환.
 *
 * 백엔드 날짜 필드 (delivery_date, next_delivery_date 등) 와 직접 비교 가능하도록
 * 동일한 'YYYY-MM-DD' 문자열을 만든다. new Date().toISOString() 은 UTC 기준이라
 * 한국 새벽 시간대에 하루 어긋날 수 있으므로 'sv-SE' 로케일 + Asia/Seoul 타임존을
 * 사용해야 한다.
 */
export function getTodayKstString(): string {
  return new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Seoul' });
}

/**
 * 'YYYY-MM-DD' 두 문자열 간 차이(일 단위)를 정수로 반환한다.
 * 양수: target 이 base 이후, 0: 같은 날, 음수: target 이 base 이전.
 *
 * 단순 연산만 하기 때문에 양쪽 모두 동일한 timezone 기준의 'YYYY-MM-DD' 문자열이어야
 * 결과가 정확하다. 권장: base = getTodayKstString() / target = 백엔드 응답 날짜.
 *
 * 잘못된 형식이 들어오면 0 을 반환한다 (호출부에서 분기하지 않아도 안전한 기본값).
 */
export function diffInDays(base: string, target: string): number {
  const baseParts = base.split('-').map(Number);
  const targetParts = target.split('-').map(Number);
  if (baseParts.length !== 3 || targetParts.length !== 3) return 0;
  const [by, bm, bd] = baseParts;
  const [ty, tm, td] = targetParts;
  if ([by, bm, bd, ty, tm, td].some((n) => Number.isNaN(n))) return 0;
  // UTC 로 만들어 DST 영향 제거. 같은 timezone 의 날짜 문자열끼리 비교하므로 결과는 KST 기준.
  const baseUtc = Date.UTC(by!, bm! - 1, bd!);
  const targetUtc = Date.UTC(ty!, tm! - 1, td!);
  return Math.round((targetUtc - baseUtc) / 86_400_000);
}
