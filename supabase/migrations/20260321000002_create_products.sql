CREATE TABLE products (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  seller_id      UUID NOT NULL REFERENCES users(id),
  name           TEXT NOT NULL,
  category       TEXT NOT NULL CHECK (category IN ('FRUIT', 'VEGETABLE', 'GRAIN', 'OTHER')),
  origin         TEXT,
  spec           TEXT,
  unit           TEXT NOT NULL CHECK (unit IN ('kg', 'box', 'piece', 'bag')),
  price_per_unit INTEGER NOT NULL,
  stock_quantity INTEGER NOT NULL DEFAULT 0,
  min_order_qty  INTEGER DEFAULT 1,
  status         TEXT NOT NULL DEFAULT 'NORMAL'
                   CHECK (status IN ('NORMAL', 'LOW_STOCK', 'OUT_OF_STOCK', 'SCHEDULED')),
  description    TEXT,
  image_url      TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at     TIMESTAMPTZ
);

CREATE TRIGGER set_updated_at BEFORE UPDATE ON products
FOR EACH ROW EXECUTE FUNCTION update_updated_at();
