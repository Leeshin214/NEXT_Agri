CREATE TABLE partners (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID NOT NULL REFERENCES users(id),
  partner_user_id UUID NOT NULL REFERENCES users(id),
  nickname        TEXT,
  status          TEXT NOT NULL DEFAULT 'ACTIVE'
                    CHECK (status IN ('ACTIVE', 'INACTIVE', 'PENDING')),
  is_favorite     BOOLEAN DEFAULT false,
  notes           TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(user_id, partner_user_id)
);

CREATE TRIGGER set_updated_at BEFORE UPDATE ON partners
FOR EACH ROW EXECUTE FUNCTION update_updated_at();
