-- ===========================================
-- chat_rooms 테이블
-- ===========================================
CREATE TABLE chat_rooms (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  order_id        UUID REFERENCES orders(id),
  seller_id       UUID NOT NULL REFERENCES users(id),
  buyer_id        UUID NOT NULL REFERENCES users(id),
  last_message    TEXT,
  last_message_at TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER set_updated_at BEFORE UPDATE ON chat_rooms
FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ===========================================
-- messages 테이블
-- ===========================================
CREATE TABLE messages (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  room_id    UUID NOT NULL REFERENCES chat_rooms(id),
  sender_id  UUID NOT NULL REFERENCES users(id),
  content    TEXT NOT NULL,
  is_read    BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
