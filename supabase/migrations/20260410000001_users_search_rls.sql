-- 인증된 사용자가 활성 사용자의 공개 프로필을 조회할 수 있도록 허용
-- 기존 users_select_self 정책은 유지 (RLS는 OR로 정책을 평가)
CREATE POLICY "users_select_active_authenticated" ON users
  FOR SELECT
  USING (
    is_active = true
    AND deleted_at IS NULL
    AND auth.uid() IS NOT NULL
  );
