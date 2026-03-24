-- ===========================================
-- 1. updated_at 자동 갱신 트리거 함수 (공용)
-- ===========================================
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ===========================================
-- 2. users 테이블
-- ===========================================
CREATE TABLE users (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  supabase_uid  UUID UNIQUE NOT NULL,
  email         TEXT UNIQUE NOT NULL,
  name          TEXT NOT NULL,
  role          TEXT NOT NULL CHECK (role IN ('SELLER', 'BUYER', 'ADMIN')),
  company_name  TEXT,
  phone         TEXT,
  profile_image TEXT,
  is_active     BOOLEAN DEFAULT true,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at    TIMESTAMPTZ
);

CREATE TRIGGER set_updated_at BEFORE UPDATE ON users
FOR EACH ROW EXECUTE FUNCTION update_updated_at();
