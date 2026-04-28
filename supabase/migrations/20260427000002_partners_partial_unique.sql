-- partners (user_id, partner_user_id) UNIQUE 제약을 soft-delete 호환 partial unique index 로 교체
-- 기존 제약은 deleted_at 무관 행 전체에 적용되어 soft-deleted 파트너 재추가 시 23505 위반 발생
-- 변경 후: 활성 행(deleted_at IS NULL) 에 대해서만 UNIQUE 적용

ALTER TABLE partners DROP CONSTRAINT IF EXISTS partners_user_id_partner_user_id_key;

CREATE UNIQUE INDEX IF NOT EXISTS partners_user_id_partner_user_id_active_key
  ON partners (user_id, partner_user_id)
  WHERE deleted_at IS NULL;
