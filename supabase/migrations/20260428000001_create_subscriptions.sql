-- ===========================================
-- subscriptions / subscription_items — 정기배송 시스템 V1.5 Phase 1
-- ===========================================
-- 정기배송(Subscription) 마스터 + 라인 + orders 추적 컬럼 + RLS
--
-- 주요 설계 포인트:
--   - subscriptions: WEEKLY/BIWEEKLY/MONTHLY 주기 + day_of_week / day_of_month
--   - 첫 회차의 next_delivery_date 는 start_date 와 동일하게 시작
--   - PAUSED → ACTIVE 전환 시 next_delivery_date 재계산 (서비스 레이어)
--   - subscription_items: 라인별 product/quantity/unit_price/unit
--   - orders 테이블에 subscription_id, subscription_round 추적 컬럼 추가
--     → 어느 정기배송의 몇 회차인지 식별 가능
--
-- RLS 정책:
--   기존 프로젝트 컨벤션을 따라 auth.uid() 와 users.supabase_uid 매핑 사용
--   (auth.uid() 는 Supabase Auth UID = users.supabase_uid 이며 users.id 가 아님).
--   이 프로젝트는 백엔드가 service_role 키로 접근하므로 RLS 우회되지만,
--   향후 anon 키 직접 접근 / Edge Functions / Realtime subscribe 시점을 대비해
--   정책을 일관되게 작성한다.

-- ===========================================
-- subscriptions 테이블 — 정기배송 마스터
-- ===========================================
CREATE TABLE IF NOT EXISTS subscriptions (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  seller_id           UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  buyer_id            UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  partner_id          UUID REFERENCES partners(id) ON DELETE SET NULL,

  frequency           TEXT NOT NULL CHECK (frequency IN ('WEEKLY', 'BIWEEKLY', 'MONTHLY')),
  day_of_week         INT  CHECK (day_of_week BETWEEN 0 AND 6),
  day_of_month        INT  CHECK (day_of_month BETWEEN 1 AND 31),

  start_date          DATE NOT NULL,
  end_date            DATE,
  next_delivery_date  DATE NOT NULL,

  status              TEXT NOT NULL DEFAULT 'ACTIVE'
                        CHECK (status IN ('ACTIVE', 'PAUSED', 'ENDED', 'CANCELLED')),
  delivery_address    TEXT,
  notes               TEXT,
  total_amount        INTEGER NOT NULL DEFAULT 0,

  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at          TIMESTAMPTZ
);

CREATE TRIGGER set_updated_at BEFORE UPDATE ON subscriptions
FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ===========================================
-- 인덱스
-- ===========================================
CREATE INDEX IF NOT EXISTS idx_subscriptions_seller
  ON subscriptions(seller_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_subscriptions_buyer
  ON subscriptions(buyer_id) WHERE deleted_at IS NULL;

-- 다음 회차 임박 정기배송 검색 (배치/스케줄러용)
CREATE INDEX IF NOT EXISTS idx_subscriptions_next_date
  ON subscriptions(next_delivery_date)
  WHERE deleted_at IS NULL AND status = 'ACTIVE';

CREATE INDEX IF NOT EXISTS idx_subscriptions_partner
  ON subscriptions(partner_id) WHERE deleted_at IS NULL;

-- ===========================================
-- subscription_items 테이블 — 정기배송 상품 라인
-- ===========================================
CREATE TABLE IF NOT EXISTS subscription_items (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  subscription_id UUID NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
  product_id      UUID NOT NULL REFERENCES products(id),
  quantity        INTEGER NOT NULL CHECK (quantity > 0),
  unit_price      INTEGER NOT NULL CHECK (unit_price >= 0),
  unit            TEXT NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_subscription_items_subscription
  ON subscription_items(subscription_id);

-- ===========================================
-- orders 테이블 — 정기배송 추적용 컬럼 추가
-- ===========================================
-- 기존 데이터에는 NULL 로 남고, 정기배송으로 자동 생성된 주문만 값 채움.
ALTER TABLE orders
  ADD COLUMN IF NOT EXISTS subscription_id   UUID REFERENCES subscriptions(id),
  ADD COLUMN IF NOT EXISTS subscription_round INT;

CREATE INDEX IF NOT EXISTS idx_orders_subscription
  ON orders(subscription_id) WHERE deleted_at IS NULL;

-- ===========================================
-- RLS 활성화
-- ===========================================
ALTER TABLE subscriptions      ENABLE ROW LEVEL SECURITY;
ALTER TABLE subscription_items ENABLE ROW LEVEL SECURITY;

-- ===========================================
-- subscriptions 정책 — buyer 또는 seller 만 접근
-- ===========================================
-- 기존 orders 패턴(orders_participant_access) 과 동일하게 supabase_uid 매핑 사용.
CREATE POLICY "subscriptions_participant_select" ON subscriptions
  FOR SELECT USING (
    buyer_id  IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
    OR seller_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
  );

CREATE POLICY "subscriptions_participant_insert" ON subscriptions
  FOR INSERT WITH CHECK (
    buyer_id  IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
    OR seller_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
  );

CREATE POLICY "subscriptions_participant_update" ON subscriptions
  FOR UPDATE USING (
    buyer_id  IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
    OR seller_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
  );

-- ===========================================
-- subscription_items 정책 — 부모 subscriptions 의 당사자만
-- ===========================================
CREATE POLICY "subscription_items_participant_select" ON subscription_items
  FOR SELECT USING (
    subscription_id IN (
      SELECT id FROM subscriptions
      WHERE deleted_at IS NULL
        AND (
          buyer_id  IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
          OR seller_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
        )
    )
  );

CREATE POLICY "subscription_items_participant_insert" ON subscription_items
  FOR INSERT WITH CHECK (
    subscription_id IN (
      SELECT id FROM subscriptions
      WHERE deleted_at IS NULL
        AND (
          buyer_id  IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
          OR seller_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
        )
    )
  );

CREATE POLICY "subscription_items_participant_update" ON subscription_items
  FOR UPDATE USING (
    subscription_id IN (
      SELECT id FROM subscriptions
      WHERE deleted_at IS NULL
        AND (
          buyer_id  IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
          OR seller_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
        )
    )
  );

CREATE POLICY "subscription_items_participant_delete" ON subscription_items
  FOR DELETE USING (
    subscription_id IN (
      SELECT id FROM subscriptions
      WHERE deleted_at IS NULL
        AND (
          buyer_id  IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
          OR seller_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
        )
    )
  );
