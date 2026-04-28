// 시스템 메시지 prefix 정의
//
// 채팅 메시지가 아래 prefix 중 하나로 시작하면 시스템 메시지로 판별해
// 가운데 회색 pill 스타일로 표시한다. 일반 사용자가 "[중요]" 같은 텍스트를
// 보내도 시스템 메시지로 오해되지 않도록 prefix를 구체적으로 명시.
//
// 백엔드 chat_ws.py 의 system broadcast 메시지(consensus 자동 생성, AI가 ...)
// 와 browse 페이지 견적 요청 메시지("[견적 요청] ...")가 모두 포함된다.
//
// 참고: WebSocket lastMessage.type === 'system' 인 경우는 별도로 처리되며
// (실시간 시스템 메시지) 이 상수와는 무관하다.
export const SYSTEM_MESSAGE_PREFIXES = [
  '[견적 요청]',
  'AI가',
  '⚠️',
  '🤖',
] as const;

export function isSystemMessageContent(content: string): boolean {
  return SYSTEM_MESSAGE_PREFIXES.some((p) => content.startsWith(p));
}
