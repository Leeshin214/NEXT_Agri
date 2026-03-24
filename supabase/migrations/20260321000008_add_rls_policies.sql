-- ===========================================
-- RLS 활성화
-- ===========================================
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE products ENABLE ROW LEVEL SECURITY;
ALTER TABLE partners ENABLE ROW LEVEL SECURITY;
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE order_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE calendar_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_rooms ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_conversations ENABLE ROW LEVEL SECURITY;

-- ===========================================
-- users 정책
-- ===========================================

-- 자신의 데이터 전체 접근
CREATE POLICY "users_self_access" ON users
  USING (supabase_uid = auth.uid());

-- 거래처로 연결된 사용자 기본 정보 조회
CREATE POLICY "users_partner_read" ON users
  FOR SELECT USING (
    id IN (
      SELECT partner_user_id FROM partners WHERE user_id IN (
        SELECT id FROM users WHERE supabase_uid = auth.uid()
      )
    )
  );

-- ===========================================
-- products 정책
-- ===========================================

-- 판매자: 자신의 상품 전체 접근
CREATE POLICY "products_seller_access" ON products
  USING (seller_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid()));

-- 구매자: 활성 상품 조회
CREATE POLICY "products_buyer_read" ON products
  FOR SELECT USING (status != 'OUT_OF_STOCK' AND deleted_at IS NULL);

-- ===========================================
-- partners 정책
-- ===========================================

-- 자신의 거래처 관계만 접근
CREATE POLICY "partners_self_access" ON partners
  USING (user_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid()));

-- 상대방도 관계 조회 가능
CREATE POLICY "partners_counterpart_read" ON partners
  FOR SELECT USING (
    partner_user_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
  );

-- ===========================================
-- orders 정책
-- ===========================================

-- 주문 당사자(buyer/seller)만 접근
CREATE POLICY "orders_participant_access" ON orders
  USING (
    buyer_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
    OR
    seller_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
  );

-- ===========================================
-- order_items 정책
-- ===========================================

-- 주문 당사자만 항목 접근
CREATE POLICY "order_items_participant_access" ON order_items
  USING (
    order_id IN (
      SELECT id FROM orders
      WHERE buyer_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
         OR seller_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
    )
  );

-- ===========================================
-- calendar_events 정책
-- ===========================================

-- 자신의 일정만 접근
CREATE POLICY "calendar_events_self_access" ON calendar_events
  USING (user_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid()));

-- ===========================================
-- chat_rooms 정책
-- ===========================================

-- 채팅방 참여자만 접근
CREATE POLICY "chat_rooms_participant_access" ON chat_rooms
  USING (
    seller_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
    OR
    buyer_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
  );

-- ===========================================
-- messages 정책
-- ===========================================

-- 채팅방 참여자만 메시지 접근
CREATE POLICY "messages_room_access" ON messages
  USING (
    room_id IN (
      SELECT id FROM chat_rooms
      WHERE seller_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
         OR buyer_id  IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
    )
  );

-- ===========================================
-- ai_conversations 정책
-- ===========================================

-- 자신의 AI 대화만 접근
CREATE POLICY "ai_conversations_self_access" ON ai_conversations
  USING (user_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid()));
