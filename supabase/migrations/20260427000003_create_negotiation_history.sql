-- ===========================================
-- negotiation_history 테이블 — 주문 협상 이력
-- ===========================================
-- 버이어/셀러가 서로 제시한 협상가(counter-offer) 이력을 보존한다.
-- ACCEPTED / REJECTED / SUPERSEDED 상태로 라이프사이클 관리.
CREATE TABLE negotiation_history (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  order_id              UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  from_user_id          UUID NOT NULL REFERENCES users(id),
  from_role             TEXT NOT NULL CHECK (from_role IN ('SELLER', 'BUYER')),
  proposed_total_amount BIGINT NOT NULL,
  proposed_items        JSONB,
  notes                 TEXT,
  status                TEXT NOT NULL DEFAULT 'PENDING'
                          CHECK (status IN ('PENDING', 'ACCEPTED', 'REJECTED', 'SUPERSEDED')),
  responded_at          TIMESTAMPTZ,
  responded_by          UUID REFERENCES users(id),
  created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ===========================================
-- 인덱스
-- ===========================================
CREATE INDEX idx_negotiation_history_order_created
  ON negotiation_history (order_id, created_at DESC);

CREATE INDEX idx_negotiation_history_order_status
  ON negotiation_history (order_id, status);

CREATE INDEX idx_negotiation_history_from_user_id
  ON negotiation_history (from_user_id);

-- ===========================================
-- RLS — 주문 당사자(buyer/seller)만 접근
-- ===========================================
ALTER TABLE negotiation_history ENABLE ROW LEVEL SECURITY;

-- SELECT: 주문 당사자
CREATE POLICY "negotiation_history_participant_read" ON negotiation_history
  FOR SELECT USING (
    order_id IN (
      SELECT id FROM orders
      WHERE buyer_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
         OR seller_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
    )
  );

-- INSERT: 주문 당사자만, 본인이 제시자(from_user_id)여야 함
CREATE POLICY "negotiation_history_participant_insert" ON negotiation_history
  FOR INSERT WITH CHECK (
    from_user_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
    AND order_id IN (
      SELECT id FROM orders
      WHERE buyer_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
         OR seller_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
    )
  );

-- UPDATE: 작성자 본인(SUPERSEDED 마킹) 또는 상대방(ACCEPTED/REJECTED)
CREATE POLICY "negotiation_history_respond_update" ON negotiation_history
  FOR UPDATE USING (
    order_id IN (
      SELECT id FROM orders
      WHERE buyer_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
         OR seller_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
    )
  );

-- ===========================================
-- orders 테이블 — 취소 메타데이터 컬럼 추가
-- ===========================================
ALTER TABLE orders
  ADD COLUMN IF NOT EXISTS cancellation_reason TEXT,
  ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS cancelled_by UUID REFERENCES users(id);
