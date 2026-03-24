-- ===========================================
-- FK 인덱스
-- ===========================================
CREATE INDEX idx_products_seller_id ON products(seller_id);
CREATE INDEX idx_partners_user_id ON partners(user_id);
CREATE INDEX idx_partners_partner_user_id ON partners(partner_user_id);
CREATE INDEX idx_orders_buyer_id ON orders(buyer_id);
CREATE INDEX idx_orders_seller_id ON orders(seller_id);
CREATE INDEX idx_order_items_order_id ON order_items(order_id);
CREATE INDEX idx_order_items_product_id ON order_items(product_id);
CREATE INDEX idx_calendar_events_user_id ON calendar_events(user_id);
CREATE INDEX idx_calendar_events_order_id ON calendar_events(order_id);
CREATE INDEX idx_chat_rooms_seller_id ON chat_rooms(seller_id);
CREATE INDEX idx_chat_rooms_buyer_id ON chat_rooms(buyer_id);
CREATE INDEX idx_chat_rooms_order_id ON chat_rooms(order_id);
CREATE INDEX idx_messages_room_id ON messages(room_id);
CREATE INDEX idx_messages_sender_id ON messages(sender_id);
CREATE INDEX idx_ai_conversations_user_id ON ai_conversations(user_id);

-- ===========================================
-- 상태/검색 인덱스
-- ===========================================
CREATE INDEX idx_users_role ON users(role);
CREATE INDEX idx_users_supabase_uid ON users(supabase_uid);
CREATE INDEX idx_products_status ON products(status);
CREATE INDEX idx_products_category ON products(category);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_orders_order_number ON orders(order_number);
CREATE INDEX idx_partners_status ON partners(status);
CREATE INDEX idx_calendar_events_event_date ON calendar_events(event_date);
CREATE INDEX idx_calendar_events_event_type ON calendar_events(event_type);
CREATE INDEX idx_messages_is_read ON messages(is_read);

-- ===========================================
-- 복합 인덱스 (쿼리 패턴 기반)
-- ===========================================

-- 판매자별 활성 상품 조회
CREATE INDEX idx_products_seller_status ON products(seller_id, status) WHERE deleted_at IS NULL;

-- 주문 상태별 최신순 조회
CREATE INDEX idx_orders_status_created ON orders(status, created_at DESC) WHERE deleted_at IS NULL;

-- 일정 날짜 범위 조회
CREATE INDEX idx_calendar_events_user_date ON calendar_events(user_id, event_date);

-- 채팅방 최신 메시지순 조회
CREATE INDEX idx_chat_rooms_last_message_at ON chat_rooms(last_message_at DESC NULLS LAST);

-- 메시지 생성시간순 조회
CREATE INDEX idx_messages_room_created ON messages(room_id, created_at);
