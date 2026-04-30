-- ===========================================
-- calendar_events ↔ subscriptions 연결 (정기배송 자동 캘린더 등록)
-- ===========================================
-- 배경:
--   PM Report #7 추천 작업 3 — "정기배송 등록 시 첫 배송일 캘린더 자동 등록".
--   기존에는 정기배송을 ACCEPT (PENDING→ACTIVE) 해도 calendar_events 에
--   첫 배송일 일정이 자동 등록되지 않아 사용자가 수동으로 캘린더에 다시 입력하던 이중 작업.
--
-- 본 마이그레이션이 하는 일:
--   1) calendar_events.subscription_id (FK → subscriptions.id) 컬럼 추가
--      - 기존 데이터는 NULL (order-linked 또는 manual 일정)
--      - subscription 으로 자동 등록된 일정만 값 채움
--   2) (subscription_id, user_id, event_date) 활성 row 1개만 보장하는 partial unique index
--      → 같은 정기배송에 대해 한 user 의 같은 날짜에 중복 INSERT 방지 (race condition 보호)
--   3) FK 컬럼 인덱스 (subscription_id 기준 cleanup 쿼리용)
--
-- 백필 정책:
--   기존 ACTIVE 정기배송에 대한 backfill 은 본 마이그레이션에서 수행하지 않는다.
--   이유:
--     - 운영 데이터 양이 적고, 사이클 부담 최소화 (Low 위험도 작업 정책)
--     - 이미 사용자가 수동 등록한 일정과 중복될 가능성
--   필요 시 별도 운영 스크립트 또는 다음 사이클에서 backfill 마이그레이션을 추가한다.
--   신규 mutation (accept / update / delete / generate_order_for_round) 부터만 동기화.
--
-- 호환성:
--   기존 partial unique index `uniq_calendar_events_active_order_user_date` 는
--   `WHERE order_id IS NOT NULL AND deleted_at IS NULL` 조건이라 subscription-only 행
--   (order_id IS NULL, subscription_id IS NOT NULL) 은 대상이 아니므로 충돌 없음.
--   본 마이그레이션이 추가하는 신규 partial unique index 와도 독립적으로 공존.

-- ===========================================
-- 1) subscription_id 컬럼 추가
-- ===========================================
ALTER TABLE calendar_events
  ADD COLUMN IF NOT EXISTS subscription_id UUID REFERENCES subscriptions(id) ON DELETE SET NULL;

COMMENT ON COLUMN calendar_events.subscription_id IS
  '정기배송으로 자동 생성된 일정을 식별. NULL=일반(주문 또는 수동) 일정.';

-- ===========================================
-- 2) partial unique index — subscription-only 활성 행 정합성
-- ===========================================
-- (subscription_id, user_id, event_date) 활성 행은 0 또는 1개.
-- subscription_id IS NULL 인 행(주문/수동 일정) 은 영향 없음.
-- soft-deleted 행도 인덱스 제외.

CREATE UNIQUE INDEX IF NOT EXISTS uniq_calendar_events_active_subscription_user_date
  ON calendar_events (subscription_id, user_id, event_date)
  WHERE subscription_id IS NOT NULL AND deleted_at IS NULL;

-- ===========================================
-- 3) subscription_id FK 인덱스
-- ===========================================
-- accept/update/delete 정기배송 시 subscription_id 기준 active row 정리/갱신용.
CREATE INDEX IF NOT EXISTS idx_calendar_events_subscription
  ON calendar_events (subscription_id)
  WHERE subscription_id IS NOT NULL AND deleted_at IS NULL;
