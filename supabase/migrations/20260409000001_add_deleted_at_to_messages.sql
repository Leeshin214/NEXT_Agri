-- messages 테이블에 deleted_at 컬럼 추가 (soft delete 지원)
ALTER TABLE messages
  ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ DEFAULT NULL;
