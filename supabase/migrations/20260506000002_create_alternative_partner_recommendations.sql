-- ===========================================
-- alternative_partner_recommendations 테이블
-- ===========================================
-- 판매자가 주문을 취소했을 때, 구매자에게 같은 상품을 파는 다른 판매자
-- 후보를 자동으로 찾아 자동 견적까지 생성한 결과를 보관하는 테이블.
--
-- 자동 트리거 흐름:
--   1) order_service.cancel_order(role=SELLER) 가 호출되어 주문이 CANCELLED 됨
--   2) alternative_partner_service.find_and_notify(order) 가 백그라운드에서 실행
--   3) LLM 으로 "본질 상품 동일성" 판별 후 상위 3개 판매자 추출
--   4) 각 판매자에게 새 QUOTE_REQUESTED 주문을 자동 생성 (auto_orders 에 ID 저장)
--   5) 이 테이블에 결과 INSERT + notifications 에 ALTERNATIVE_PARTNERS 알림 emit
--
-- candidates JSONB 구조 (예시):
--   [
--     {
--       "seller_id": "<uuid>", "seller_name": "...", "seller_company": "...",
--       "product_id": "<uuid>", "product_name": "창원 감자",
--       "stock_quantity": 100, "price_per_unit": 3000, "unit": "kg",
--       "trade_count": 5, "last_trade_date": "2026-04-30T...",
--       "auto_order_id": "<uuid|null>",         -- 자동 견적 주문 생성 성공 시 UUID
--       "auto_order_number": "ORD-...",          -- 자동 생성 주문 번호 (UI 노출용)
--       "auto_order_error": null                 -- 자동 견적 실패 시 에러 메시지
--     }, ...
--   ]
--
-- found_count: candidates.length (0 이면 "대체 판매자를 찾지 못함")
--
-- 한 cancelled_order 당 1 row 만 — UNIQUE 제약으로 보장 (재실행 시 UPSERT).

CREATE TABLE IF NOT EXISTS alternative_partner_recommendations (
  id                 UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  cancelled_order_id UUID        NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  buyer_id           UUID        NOT NULL REFERENCES users(id)  ON DELETE CASCADE,
  candidates         JSONB       NOT NULL DEFAULT '[]'::jsonb,
  reason             TEXT        NOT NULL DEFAULT 'SELLER_CANCELLED',
  found_count        INTEGER     NOT NULL DEFAULT 0,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 한 cancelled_order 당 1 row
CREATE UNIQUE INDEX IF NOT EXISTS idx_alt_recs_order
  ON alternative_partner_recommendations(cancelled_order_id);

-- 구매자별 최신순 조회용
CREATE INDEX IF NOT EXISTS idx_alt_recs_buyer_created
  ON alternative_partner_recommendations(buyer_id, created_at DESC);

-- ===========================================
-- RLS — 본인(buyer) 만 SELECT
-- ===========================================
ALTER TABLE alternative_partner_recommendations ENABLE ROW LEVEL SECURITY;

CREATE POLICY "alt_recs_select_own"
  ON alternative_partner_recommendations
  FOR SELECT USING (
    buyer_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
  );
-- INSERT/UPDATE 정책 없음 → service_role 만 가능 (백엔드 전용).

-- ===========================================
-- notifications.type CHECK 제약 확장 — ALTERNATIVE_PARTNERS 추가
-- ===========================================
-- 기존 제약을 동적으로 찾아 DROP 후 재정의 (제약 이름이 환경마다 다를 수 있음).
DO $$
DECLARE
  cname TEXT;
BEGIN
  FOR cname IN
    SELECT conname
    FROM pg_constraint
    WHERE conrelid = 'notifications'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%type%'
  LOOP
    EXECUTE format('ALTER TABLE notifications DROP CONSTRAINT %I', cname);
  END LOOP;

  ALTER TABLE notifications
    ADD CONSTRAINT notifications_type_check
    CHECK (type IN (
      'NEW_MESSAGE',
      'COUNTER_OFFER',
      'OFFER_ACCEPTED',
      'OFFER_REJECTED',
      'DELIVERY_DATE_CHANGE',
      'DELIVERY_DATE_ACCEPTED',
      'DELIVERY_DATE_REJECTED',
      'ORDER_STATUS',
      'ALTERNATIVE_PARTNERS'
    ));
END $$;
