-- =============================================================
-- RLS 정책 재정의 (20260325)
-- 기존 정책을 DROP 후 스펙에 맞게 재생성한다.
-- service_role은 RLS를 자동으로 우회하므로
-- 아래 정책은 authenticated / anon 역할에만 적용된다.
-- =============================================================

-- ===========================================
-- RLS 활성화 (이미 활성화된 경우 무시됨)
-- ===========================================
ALTER TABLE users              ENABLE ROW LEVEL SECURITY;
ALTER TABLE products           ENABLE ROW LEVEL SECURITY;
ALTER TABLE orders             ENABLE ROW LEVEL SECURITY;
ALTER TABLE order_items        ENABLE ROW LEVEL SECURITY;
ALTER TABLE partners           ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_rooms         ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages           ENABLE ROW LEVEL SECURITY;
ALTER TABLE calendar_events    ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_conversations   ENABLE ROW LEVEL SECURITY;

-- ===========================================
-- 기존 정책 제거 (재생성 전 충돌 방지)
-- ===========================================
DROP POLICY IF EXISTS "users_self_access"                ON users;
DROP POLICY IF EXISTS "users_partner_read"               ON users;

DROP POLICY IF EXISTS "products_seller_access"           ON products;
DROP POLICY IF EXISTS "products_buyer_read"              ON products;

DROP POLICY IF EXISTS "orders_participant_access"        ON orders;

DROP POLICY IF EXISTS "order_items_participant_access"   ON order_items;

DROP POLICY IF EXISTS "partners_self_access"             ON partners;
DROP POLICY IF EXISTS "partners_counterpart_read"        ON partners;

DROP POLICY IF EXISTS "chat_rooms_participant_access"    ON chat_rooms;

DROP POLICY IF EXISTS "messages_room_access"             ON messages;

DROP POLICY IF EXISTS "calendar_events_self_access"      ON calendar_events;

DROP POLICY IF EXISTS "ai_conversations_self_access"     ON ai_conversations;

-- ===========================================
-- users
-- 본인 행만 SELECT/UPDATE 가능
-- INSERT는 service role만 (auth trigger에서 처리)
-- ===========================================
CREATE POLICY "users_select_self" ON users
  FOR SELECT
  USING (supabase_uid = auth.uid());

CREATE POLICY "users_update_self" ON users
  FOR UPDATE
  USING (supabase_uid = auth.uid());

-- ===========================================
-- products
-- SELECT: 모든 인증 사용자가 deleted_at IS NULL 인 상품 조회 가능
-- INSERT/UPDATE/DELETE: seller_id가 본인인 경우만
-- ===========================================
CREATE POLICY "products_select_all" ON products
  FOR SELECT
  USING (deleted_at IS NULL);

CREATE POLICY "products_insert_seller" ON products
  FOR INSERT
  WITH CHECK (
    seller_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
  );

CREATE POLICY "products_update_seller" ON products
  FOR UPDATE
  USING (
    seller_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
  );

CREATE POLICY "products_delete_seller" ON products
  FOR DELETE
  USING (
    seller_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
  );

-- ===========================================
-- orders
-- SELECT: buyer_id 또는 seller_id가 본인인 경우
-- INSERT: buyer만 (본인이 buyer_id로 지정된 경우)
-- UPDATE: buyer_id 또는 seller_id가 본인인 경우
-- ===========================================
CREATE POLICY "orders_select_participant" ON orders
  FOR SELECT
  USING (
    buyer_id  IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
    OR
    seller_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
  );

CREATE POLICY "orders_insert_buyer" ON orders
  FOR INSERT
  WITH CHECK (
    buyer_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
  );

CREATE POLICY "orders_update_participant" ON orders
  FOR UPDATE
  USING (
    buyer_id  IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
    OR
    seller_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
  );

-- ===========================================
-- order_items
-- SELECT: 연결된 order의 buyer_id 또는 seller_id가 본인인 경우
-- ===========================================
CREATE POLICY "order_items_select_participant" ON order_items
  FOR SELECT
  USING (
    order_id IN (
      SELECT id FROM orders
      WHERE buyer_id  IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
         OR seller_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
    )
  );

-- ===========================================
-- partners
-- user_id가 본인인 경우만 모든 작업 가능
-- ===========================================
CREATE POLICY "partners_all_self" ON partners
  FOR ALL
  USING (
    user_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
  )
  WITH CHECK (
    user_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
  );

-- ===========================================
-- chat_rooms
-- seller_id 또는 buyer_id가 본인인 경우 모든 작업 가능
-- ===========================================
CREATE POLICY "chat_rooms_all_participant" ON chat_rooms
  FOR ALL
  USING (
    seller_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
    OR
    buyer_id  IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
  )
  WITH CHECK (
    seller_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
    OR
    buyer_id  IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
  );

-- ===========================================
-- messages
-- 연결된 chat_room의 seller_id 또는 buyer_id가 본인인 경우 SELECT/INSERT
-- ===========================================
CREATE POLICY "messages_select_participant" ON messages
  FOR SELECT
  USING (
    room_id IN (
      SELECT id FROM chat_rooms
      WHERE seller_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
         OR buyer_id  IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
    )
  );

CREATE POLICY "messages_insert_participant" ON messages
  FOR INSERT
  WITH CHECK (
    room_id IN (
      SELECT id FROM chat_rooms
      WHERE seller_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
         OR buyer_id  IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
    )
  );

-- ===========================================
-- calendar_events
-- user_id가 본인인 경우만 모든 작업 가능
-- ===========================================
CREATE POLICY "calendar_events_all_self" ON calendar_events
  FOR ALL
  USING (
    user_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
  )
  WITH CHECK (
    user_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
  );

-- ===========================================
-- ai_conversations
-- user_id가 본인인 경우만 모든 작업 가능
-- ===========================================
CREATE POLICY "ai_conversations_all_self" ON ai_conversations
  FOR ALL
  USING (
    user_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
  )
  WITH CHECK (
    user_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
  );
