-- =============================================================
-- buyer_inventories RLS 무한재귀(42P17) 긴급 수정
-- =============================================================
-- 증상:
--   2026-05-03 마이그레이션 (20260503000001_create_buyer_inventories.sql)
--   적용 직후 운영 PostgREST 가 모든 anon/authenticated SELECT 에 대해
--   42P17 "infinite recursion detected in policy for relation users"
--   를 반환. /rest/v1/products, /rest/v1/orders, /rest/v1/users,
--   /rest/v1/buyer_inventories 모두 동일.
--   (service_role 키 호출은 정상 — RLS 우회되므로 재현 안 됨.)
--
-- 원인 분석:
--   buyer_inventories 의 새 SELECT/UPDATE 정책 본문은
--   `buyer_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())`
--   패턴을 사용. 이 자체는 subscriptions/notifications 등
--   다른 테이블에서 검증된 패턴과 동일하지만,
--   카탈로그 변경(새 테이블/정책 추가)으로 PostgreSQL 의 RLS plan
--   invalidation 이 발생하면서, users 테이블에 잠재되어 있던
--   자기참조 cycle (또는 OR 정책 cross-evaluation) 이 더 이상
--   기존의 운 좋은 평가 순서로 풀리지 않게 되었다.
--
-- 회피 전략:
--   buyer_inventories 의 RLS 정책 본문에서 `SELECT FROM users` 를
--   직접 수행하지 않는다. 대신 `auth.uid()` ↔ `users.id` 매핑을
--   SECURITY DEFINER 함수 안에 캡슐화해 RLS 평가를 우회한다.
--
--   - 함수는 RLS 평가 컨텍스트 바깥에서 단일 SELECT 를 수행 →
--     users 정책이 다시 트리거되지 않음 → 무한재귀 차단.
--   - STABLE 마킹으로 같은 트랜잭션 내 동일 입력엔 결과 캐시.
--   - SET search_path = public, pg_temp 로 search_path injection 차단.
--   - 기존 마이그레이션(20260503000001) 의 테이블/인덱스/컬럼 정의는
--     건드리지 않는다. 정책만 DROP → 신규 정책 재생성.
--
-- 영향 범위:
--   buyer_inventories 만 패턴 변경. 다른 테이블(users/products/orders/
--   partners/subscriptions/notifications/...)의 RLS 는 일체 수정 없음.
--   추후 동일 무한재귀가 다른 테이블에서도 재발하면 같은 helper 함수를
--   재사용해 점진적으로 마이그레이션 가능.
-- =============================================================


-- ===========================================
-- 1) auth.uid() ↔ users.id 매핑 헬퍼 함수
-- ===========================================
-- SECURITY DEFINER 로 RLS 우회 — 이 함수 안의 SELECT 는
-- users 의 RLS 정책을 평가하지 않으므로 자기참조 cycle 이 발생할 수 없다.
-- STABLE 로 같은 트랜잭션 안에서 동일 인자에 대해 결과 캐시.
-- SET search_path 명시는 SECURITY DEFINER 함수의 보안 모범 사례.
CREATE OR REPLACE FUNCTION public.current_app_user_id()
RETURNS UUID
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT id FROM public.users
  WHERE supabase_uid = auth.uid()
  LIMIT 1
$$;

-- 함수 자체에 대한 EXECUTE 권한은 anon/authenticated 모두 허용
-- (RLS 정책 본문에서 호출 가능해야 하므로).
GRANT EXECUTE ON FUNCTION public.current_app_user_id() TO anon, authenticated, service_role;


-- ===========================================
-- 2) 기존 buyer_inventories 정책 제거
-- ===========================================
-- 20260503000001 에서 만든 두 정책을 안전하게 DROP.
-- IF EXISTS 로 멱등성 보장.
DROP POLICY IF EXISTS "buyer_inventories_select_own" ON buyer_inventories;
DROP POLICY IF EXISTS "buyer_inventories_update_own" ON buyer_inventories;


-- ===========================================
-- 3) 신규 정책 — SELECT 서브쿼리 대신 헬퍼 함수 사용
-- ===========================================
-- 본문이 더 이상 users 를 직접 SELECT 하지 않는다 →
-- users 의 RLS 정책이 재귀 평가될 일이 없음.
-- 의미는 동일: 본인 buyer_id 행만 접근.

CREATE POLICY "buyer_inventories_select_own" ON buyer_inventories
  FOR SELECT USING (
    buyer_id = public.current_app_user_id()
  );

CREATE POLICY "buyer_inventories_update_own" ON buyer_inventories
  FOR UPDATE USING (
    buyer_id = public.current_app_user_id()
  );

-- INSERT/DELETE 정책은 의도적으로 정의하지 않는다.
-- → 클라이언트 직접 INSERT/DELETE 차단, service_role 만 가능
--   (자동 누적 + soft delete via PATCH).
-- 기존 20260503000001 의 설계 그대로 유지.
