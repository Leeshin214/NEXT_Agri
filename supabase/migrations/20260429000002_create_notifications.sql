-- ===========================================
-- notifications 테이블 — 사용자 알림 (종 아이콘)
-- ===========================================
-- 가격 협상 / 납품일 변경 / 주문 상태 변경 / 신규 채팅 메시지 4종 알림.
-- 채팅 시스템 메시지(messages 테이블) 와 별개로 우상단 종 아이콘 패턴 전용.
-- 본인 알림만 조회·수정 (insert 는 service role 만 — 서버 emit).
-- 기존 negotiation_history 마이그레이션 RLS 패턴(auth.uid() ↔ users.supabase_uid) 을 따른다.

CREATE TABLE notifications (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  type       TEXT NOT NULL CHECK (type IN (
                'NEW_MESSAGE',
                'COUNTER_OFFER',
                'OFFER_ACCEPTED',
                'OFFER_REJECTED',
                'DELIVERY_DATE_CHANGE',
                'DELIVERY_DATE_ACCEPTED',
                'DELIVERY_DATE_REJECTED',
                'ORDER_STATUS')),
  title      TEXT NOT NULL,
  body       TEXT NOT NULL,
  link_url   TEXT,
  order_id   UUID REFERENCES orders(id)      ON DELETE SET NULL,
  room_id    UUID REFERENCES chat_rooms(id)  ON DELETE SET NULL,
  is_read    BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  read_at    TIMESTAMPTZ
);

-- ===========================================
-- 인덱스
-- ===========================================
-- 미읽음 빠른 조회 (종 아이콘 카운트, 알림 패널 최신순)
CREATE INDEX idx_notifications_user_unread
  ON notifications(user_id, created_at DESC) WHERE is_read = false;

-- 전체 최근 알림 (페이지네이션, 읽음 포함 30건 등)
CREATE INDEX idx_notifications_user_recent
  ON notifications(user_id, created_at DESC);

-- ===========================================
-- RLS — 본인 알림만 조회·수정 (insert 는 service role 만)
-- (negotiation_history / delivery_date_change_history 와 동일 패턴:
--  auth.uid() ↔ users.supabase_uid 매핑)
-- ===========================================
ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;

-- SELECT: 본인 알림만
CREATE POLICY "notifications_select_own" ON notifications
  FOR SELECT USING (
    user_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
  );

-- UPDATE: 본인 알림만 (읽음 처리)
CREATE POLICY "notifications_update_own" ON notifications
  FOR UPDATE USING (
    user_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
  );

-- INSERT 정책 미정의 → service_role 만 INSERT 가능 (anon/authenticated 차단).
-- 백엔드 서비스가 service_role 키로 emit 하므로 정상 동작.

-- ===========================================
-- Supabase Realtime publication 추가
-- (테이블 변경 broadcast — 프론트가 종 아이콘 즉시 갱신 가능)
-- ===========================================
ALTER PUBLICATION supabase_realtime ADD TABLE notifications;
