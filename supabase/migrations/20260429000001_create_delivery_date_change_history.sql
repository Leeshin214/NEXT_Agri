-- ===========================================
-- delivery_date_change_history 테이블 — 납품일 변경 요청 이력
-- ===========================================
-- 주문 당사자(SELLER/BUYER)가 납품일 변경을 제안 → 상대방이 ACCEPTED/REJECTED 응답.
-- ACCEPTED 시 orders.delivery_date 가 갱신되고 calendar_events / 채팅 시스템 메시지가 자동 동기화된다.
-- 기존 negotiation_history (가격 협상) 와 동일한 라이프사이클·RLS 패턴을 따른다.

CREATE TABLE delivery_date_change_history (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  order_id                 UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  from_user_id             UUID NOT NULL REFERENCES users(id),
  from_role                TEXT NOT NULL CHECK (from_role IN ('SELLER', 'BUYER')),
  proposed_delivery_date   DATE NOT NULL,
  notes                    TEXT,
  status                   TEXT NOT NULL DEFAULT 'PENDING'
                             CHECK (status IN ('PENDING', 'ACCEPTED', 'REJECTED', 'SUPERSEDED')),
  responded_at             TIMESTAMPTZ,
  responded_by             UUID REFERENCES users(id),
  created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ===========================================
-- 인덱스
-- ===========================================
CREATE INDEX idx_ddch_order_created
  ON delivery_date_change_history (order_id, created_at DESC);

-- 진행 중 PENDING 만 빠르게 조회 (수락/거절 처리, SUPERSEDED 마킹용)
CREATE INDEX idx_ddch_order_pending
  ON delivery_date_change_history (order_id)
  WHERE status = 'PENDING';

CREATE INDEX idx_ddch_from_user_id
  ON delivery_date_change_history (from_user_id);

-- ===========================================
-- updated_at 트리거 (프로젝트 표준)
-- ===========================================
CREATE TRIGGER set_updated_at_delivery_date_change_history
  BEFORE UPDATE ON delivery_date_change_history
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ===========================================
-- RLS — 주문 당사자(buyer/seller)만 접근
-- (negotiation_history 와 동일 패턴: auth.uid() ↔ users.supabase_uid 매핑)
-- ===========================================
ALTER TABLE delivery_date_change_history ENABLE ROW LEVEL SECURITY;

-- SELECT: 주문 당사자
CREATE POLICY "ddch_participant_read" ON delivery_date_change_history
  FOR SELECT USING (
    order_id IN (
      SELECT id FROM orders
      WHERE buyer_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
         OR seller_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
    )
  );

-- INSERT: 주문 당사자만, 본인이 제시자(from_user_id)여야 함
CREATE POLICY "ddch_participant_insert" ON delivery_date_change_history
  FOR INSERT WITH CHECK (
    from_user_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
    AND order_id IN (
      SELECT id FROM orders
      WHERE buyer_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
         OR seller_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
    )
  );

-- UPDATE: 작성자 본인(SUPERSEDED 마킹) 또는 상대방(ACCEPTED/REJECTED)
CREATE POLICY "ddch_respond_update" ON delivery_date_change_history
  FOR UPDATE USING (
    order_id IN (
      SELECT id FROM orders
      WHERE buyer_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
         OR seller_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
    )
  );

-- ===========================================
-- messages.message_type CHECK 제약 확장
-- ===========================================
-- 납품일 변경 시스템 메시지 3종 추가:
--   DELIVERY_DATE_CHANGE   — 변경 요청 제시
--   DELIVERY_DATE_ACCEPTED — 수락
--   DELIVERY_DATE_REJECTED — 거절
-- 기존 CHECK 제약(20260427000004_message_types) 을 DROP 후 재생성.
ALTER TABLE messages DROP CONSTRAINT IF EXISTS messages_message_type_check;

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
    'DELIVERY_DATE_CHANGE',
    'DELIVERY_DATE_ACCEPTED',
    'DELIVERY_DATE_REJECTED'
  ));
