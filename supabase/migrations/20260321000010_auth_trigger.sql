-- ===========================================
-- Supabase Auth -> users 테이블 자동 동기화 트리거
-- 회원가입 시 auth.users에 레코드 생성되면
-- public.users에 프로필 자동 생성
-- ===========================================

CREATE OR REPLACE FUNCTION handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO public.users (supabase_uid, email, name, role, company_name)
  VALUES (
    NEW.id,
    NEW.email,
    COALESCE(NEW.raw_user_meta_data->>'name', ''),
    COALESCE(NEW.raw_user_meta_data->>'role', 'BUYER'),
    COALESCE(NEW.raw_user_meta_data->>'company_name', '')
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION handle_new_user();
