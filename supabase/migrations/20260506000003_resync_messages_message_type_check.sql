-- ===========================================
-- messages.message_type CHECK 제약 재동기화
-- ===========================================
-- 운영 DB 의 실제 CHECK 제약이 누적 마이그레이션과 불일치 — 'ORDER_CANCELLED',
-- 'DELIVERY_DATE_REJECTED', 'ORDER_STATUS', 'CANCEL_REQUESTED',
-- 'CANCEL_REQUEST_REJECTED' 가 거절되어 cancel_order / 카드 액션 흐름의
-- _emit_chat_event 가 23514 로 실패하고 있다 (try/except 가 가려서 가시성도 낮음).
--
-- 이전 마이그레이션 20260505000002 의 DO $$ 블록이 어떤 이유(트랜잭션 롤백 등)로
-- 운영 DB 에 반영되지 못한 것으로 보인다. 본 마이그레이션은 코드에서 실제로 emit
-- 하는 모든 message_type 을 한 번에 보강한다.
--
-- 백엔드 코드에서 사용하는 message_type 전수 (2026-05-06 기준):
--   - TEXT, SYSTEM
--   - COUNTER_OFFER, OFFER_ACCEPTED, OFFER_REJECTED
--   - DELIVERY_DATE_CHANGE, DELIVERY_DATE_ACCEPTED, DELIVERY_DATE_REJECTED
--   - ORDER_STATUS, ORDER_CANCELLED
--   - CANCEL_REQUESTED, CANCEL_REQUEST_REJECTED

DO $$
DECLARE
  cname TEXT;
BEGIN
  -- 기존 message_type 관련 CHECK 제약 모두 DROP (제약 이름이 환경마다 다를 수 있음)
  FOR cname IN
    SELECT conname
    FROM pg_constraint
    WHERE conrelid = 'messages'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%message_type%'
  LOOP
    EXECUTE format('ALTER TABLE messages DROP CONSTRAINT %I', cname);
  END LOOP;

  ALTER TABLE messages
    ADD CONSTRAINT messages_message_type_check
    CHECK (message_type IN (
      'TEXT',
      'SYSTEM',
      'COUNTER_OFFER',
      'OFFER_ACCEPTED',
      'OFFER_REJECTED',
      'DELIVERY_DATE_CHANGE',
      'DELIVERY_DATE_ACCEPTED',
      'DELIVERY_DATE_REJECTED',
      'ORDER_STATUS',
      'ORDER_CANCELLED',
      'CANCEL_REQUESTED',
      'CANCEL_REQUEST_REJECTED'
    )) NOT VALID;
END $$;
