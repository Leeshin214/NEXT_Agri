-- 주문 협상 ↔ 채팅 양방향 연결 — messages 테이블 확장
-- message_type: 메시지 종류 분류 (TEXT 일반, SYSTEM 시스템, COUNTER_OFFER 협상가 제시, etc.)
-- metadata: 협상가/주문 관련 부가 정보 (offer_id, proposed_total_amount, from_role 등)
--
-- 기존 메시지는 모두 message_type='TEXT' 로 마이그레이션됨 (DEFAULT 적용).
-- send_system_message 가 INSERT 한 [SYSTEM] prefix 메시지도 기존엔 message_type 컬럼이 없었으므로
-- DB 상으로는 TEXT 로 분류된다. 새로 발송되는 시스템 메시지부터 'SYSTEM' 으로 정확히 분류.

ALTER TABLE messages
  ADD COLUMN IF NOT EXISTS message_type TEXT NOT NULL DEFAULT 'TEXT'
    CHECK (message_type IN (
      'TEXT',
      'SYSTEM',
      'COUNTER_OFFER',
      'OFFER_ACCEPTED',
      'OFFER_REJECTED',
      'ORDER_STATUS',
      'ORDER_CANCELLED'
    )),
  ADD COLUMN IF NOT EXISTS metadata JSONB;

-- room_id + message_type 복합 인덱스 — 채팅방의 협상 이벤트만 빠르게 조회 가능
CREATE INDEX IF NOT EXISTS idx_messages_room_type ON messages(room_id, message_type);
