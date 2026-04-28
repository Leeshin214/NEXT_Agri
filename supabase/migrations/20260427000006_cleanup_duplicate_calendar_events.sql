-- ===========================================
-- calendar_events 중복 데이터 정리 + 재발 방지 (2026-04-27)
-- ===========================================
-- 배경:
--   판매자 캘린더에 동일 (order_id, user_id, event_date) 조합의 active row 가
--   수십 건씩 누적된 사례 발견. 주문/견적은 4건뿐인데 캘린더는 수십개 표시되는 정합성 버그.
--
-- 근본 원인:
--   1) order_service._sync_calendar_events_for_order_sync 의 race condition
--      또는 이전 _ensure_order_events_for_user backfill 폭주 시기에
--      중복 INSERT 가 누적된 것으로 추정.
--   2) (order_id, user_id, event_date) 조합에 UNIQUE 제약이 없어 DB 차원에서 막을 수 없었음.
--   3) 주문 납기일이 변경되면 옛 event_date 의 row 가 잔존할 가능성.
--
-- 본 마이그레이션은 다음 3가지를 수행한다:
--   A) 같은 (order_id, user_id, event_date) 그룹에서 가장 최신 active row 1개만 남기고
--      나머지는 soft-delete
--   B) 주문이 CANCELLED / soft-deleted 상태인데 active calendar_events 가 잔존하는 경우 정리
--   C) 주문의 현재 delivery_date 와 다른 event_date 를 가진 잔존 active row 정리
--   D) 향후 중복 누적 방지를 위한 partial unique index 생성
--      (active row + order_id IS NOT NULL 인 경우에만)


-- =========================================================
-- A) 같은 (order_id, user_id, event_date) 그룹별로 1개만 남기고 나머지 soft-delete
-- =========================================================
-- ROW_NUMBER() 로 그룹별 순위를 매기고 rn > 1 인 row 만 soft-delete.
-- 정렬 기준: updated_at DESC, created_at DESC, id (가장 최신 active row 보존).
-- WHERE 절로 active(deleted_at IS NULL) + order_id IS NOT NULL 만 대상.

WITH ranked AS (
  SELECT
    id,
    ROW_NUMBER() OVER (
      PARTITION BY order_id, user_id, event_date
      ORDER BY updated_at DESC, created_at DESC, id
    ) AS rn
  FROM calendar_events
  WHERE deleted_at IS NULL
    AND order_id IS NOT NULL
)
UPDATE calendar_events
SET deleted_at = NOW(),
    updated_at = NOW()
WHERE id IN (SELECT id FROM ranked WHERE rn > 1);


-- =========================================================
-- B) 주문이 CANCELLED 또는 soft-deleted 인데 calendar_events 가 active 인 row 정리
-- =========================================================
-- order_service._sync_calendar_events_for_order_sync 가 이런 경우 active row 를
-- soft-delete 하도록 되어있지만, 과거에 동기화 누락으로 잔존한 row 가 있을 수 있음.

UPDATE calendar_events ce
SET deleted_at = NOW(),
    updated_at = NOW()
FROM orders o
WHERE ce.order_id = o.id
  AND ce.deleted_at IS NULL
  AND (o.status = 'CANCELLED' OR o.deleted_at IS NOT NULL);


-- =========================================================
-- C) 주문의 현재 delivery_date 와 다른 event_date 를 가진 잔존 active row 정리
-- =========================================================
-- 주문 납기일이 변경되었지만 옛 event_date 의 calendar_events 가 soft-delete 되지 않고
-- 잔존하는 케이스. delivery_date 가 NULL 이면 정리 대상 제외 (created_at fallback 케이스 보호).
-- 주의: 활성 주문(non-CANCELLED, non-deleted) 만 대상으로 한다.

UPDATE calendar_events ce
SET deleted_at = NOW(),
    updated_at = NOW()
FROM orders o
WHERE ce.order_id = o.id
  AND ce.deleted_at IS NULL
  AND o.deleted_at IS NULL
  AND o.status <> 'CANCELLED'
  AND o.delivery_date IS NOT NULL
  AND ce.event_date <> o.delivery_date;


-- =========================================================
-- D) 향후 중복 누적 방지: partial unique index
-- =========================================================
-- (order_id, user_id, event_date) 조합에 대해 active row + order_id IS NOT NULL 인 경우만
-- UNIQUE 적용. soft-deleted 행이나 manual event(order_id IS NULL) 는 영향 없음.
--
-- 이로써:
--   - 동일 (order_id, user_id, event_date) active row 는 항상 정확히 0 또는 1개
--   - race condition 으로 동시 INSERT 시도 시 DB 가 23505 로 차단
--   - manual 일정(order_id IS NULL) 은 자유롭게 추가 가능
--
-- 주의: 이 마이그레이션은 위 A/B/C 정리 스텝 이후에 실행되어야 충돌 없이 인덱스가 생성된다.

CREATE UNIQUE INDEX IF NOT EXISTS uniq_calendar_events_active_order_user_date
  ON calendar_events (order_id, user_id, event_date)
  WHERE order_id IS NOT NULL AND deleted_at IS NULL;
