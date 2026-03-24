-- ===========================================
-- orders 테이블
-- ===========================================
CREATE TABLE orders (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  order_number     TEXT UNIQUE NOT NULL,
  buyer_id         UUID NOT NULL REFERENCES users(id),
  seller_id        UUID NOT NULL REFERENCES users(id),
  status           TEXT NOT NULL DEFAULT 'QUOTE_REQUESTED'
                     CHECK (status IN (
                       'QUOTE_REQUESTED', 'NEGOTIATING', 'CONFIRMED',
                       'PREPARING', 'SHIPPING', 'COMPLETED', 'CANCELLED'
                     )),
  total_amount     INTEGER,
  delivery_date    DATE,
  delivery_address TEXT,
  notes            TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at       TIMESTAMPTZ
);

CREATE TRIGGER set_updated_at BEFORE UPDATE ON orders
FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ===========================================
-- order_items 테이블
-- ===========================================
CREATE TABLE order_items (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  order_id    UUID NOT NULL REFERENCES orders(id),
  product_id  UUID NOT NULL REFERENCES products(id),
  quantity    INTEGER NOT NULL,
  unit_price  INTEGER NOT NULL,
  subtotal    INTEGER NOT NULL,
  notes       TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
