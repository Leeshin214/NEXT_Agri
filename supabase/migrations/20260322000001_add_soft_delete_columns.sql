-- partners 테이블에 deleted_at 추가
ALTER TABLE partners ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

-- calendar_events 테이블에 deleted_at 추가
ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
