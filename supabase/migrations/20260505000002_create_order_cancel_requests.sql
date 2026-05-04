-- 주문 취소 요청 테이블
-- 구매자가 CONFIRMED 상태 주문에 대해 판매자에게 취소 승인을 요청하는 워크플로우.
-- PREPARING/SHIPPING 단계에서는 구매자가 취소 요청조차 불가 (백엔드 가드).

CREATE TABLE IF NOT EXISTS order_cancel_requests (
  id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  order_id     UUID        NOT NULL REFERENCES orders(id),
  requester_id UUID        NOT NULL REFERENCES users(id),
  reason       TEXT        NOT NULL,
  status       TEXT        NOT NULL DEFAULT 'PENDING'
                 CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED')),
  responded_at TIMESTAMPTZ,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cancel_requests_order_id
  ON order_cancel_requests(order_id);

CREATE INDEX IF NOT EXISTS idx_cancel_requests_order_pending
  ON order_cancel_requests(order_id, status)
  WHERE status = 'PENDING';

-- messages.message_type CHECK 확장: CANCEL_REQUESTED, CANCEL_REQUEST_REJECTED 추가.
-- NOT VALID: 기존 row 는 검증하지 않고 새 INSERT/UPDATE 에만 적용.
DO $$
DECLARE
  cname TEXT;
BEGIN
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
      'ORDER_STATUS',
      'ORDER_CANCELLED',
      'CANCEL_REQUESTED',
      'CANCEL_REQUEST_REJECTED'
    )) NOT VALID;
END $$;
