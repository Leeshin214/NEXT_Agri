-- ===========================================
-- V1.6 — 거래처 + 정기배송 양방향 승인 모델
-- ===========================================
-- 목표:
--   1) partners.status 에 PENDING_OUTGOING / PENDING_INCOMING 추가
--      - PENDING_OUTGOING: 본인이 보낸 요청 (수락 대기 중, 본인은 수락 불가)
--      - PENDING_INCOMING: 상대가 본인에게 보낸 요청 (본인이 수락/거절 가능)
--      - 기존 ACTIVE / INACTIVE / PENDING 은 호환을 위해 유지 (기존 데이터 영향 없음)
--   2) subscriptions.status 에 PENDING / REJECTED 추가
--      - PENDING: 요청자가 만든 직후, 상대 수락 대기
--      - REJECTED: 상대가 거절 (이력 보존; soft-delete 와 별도)
--      - 기존 ACTIVE / PAUSED / ENDED / CANCELLED 유지
--   3) subscriptions.created_by 컬럼 추가
--      - 누가 정기배송 요청을 만들었는지 추적 (수락 권한 판단용)
--      - created_by != user 인 당사자만 accept / reject 가능

-- ===========================================
-- 1) partners.status CHECK 제약 확장
-- ===========================================
ALTER TABLE partners
  DROP CONSTRAINT IF EXISTS partners_status_check;

ALTER TABLE partners
  ADD CONSTRAINT partners_status_check
  CHECK (status IN ('ACTIVE', 'INACTIVE', 'PENDING', 'PENDING_OUTGOING', 'PENDING_INCOMING'));

-- ===========================================
-- 2) subscriptions.status CHECK 제약 확장
-- ===========================================
ALTER TABLE subscriptions
  DROP CONSTRAINT IF EXISTS subscriptions_status_check;

ALTER TABLE subscriptions
  ADD CONSTRAINT subscriptions_status_check
  CHECK (status IN ('PENDING', 'ACTIVE', 'PAUSED', 'ENDED', 'CANCELLED', 'REJECTED'));

-- ===========================================
-- 3) subscriptions.created_by 컬럼 추가
-- ===========================================
-- 기존 데이터는 NULL — 생성자 정보가 없으므로 accept 권한 판단 시
-- 백엔드는 NULL 인 경우 "이전 모델로 만든 정기배송" 으로 보고 일반 update 로만 처리.
ALTER TABLE subscriptions
  ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES users(id);

-- 인덱스: created_by 기준 조회 (내가 만든 정기배송 요청 / 받은 요청 등)
CREATE INDEX IF NOT EXISTS idx_subscriptions_created_by
  ON subscriptions(created_by) WHERE deleted_at IS NULL;
