-- soft delete 된 주문 (orders.deleted_at IS NOT NULL) 의 살아있는 calendar_events 를 일괄 soft delete
--
-- 배경:
--   delete_order (주문 soft delete) 가 _sync_calendar_events_for_order 를 호출하지 않아서
--   캘린더에 orphan 일정이 남는 케이스가 운영 데이터에 누적됨.
--   캘린더에는 "주문 ORD-... - 상태" 형식으로 표시되지만 주문/견적 관리 페이지엔 안 보이고
--   주문 상세 진입 시 404 가 뜨는 문제 발생.
--
--   코드 수정 (next commit) 으로 앞으로의 delete_order 는 자동 정리되지만, 이미 누적된
--   orphan 일정은 이 마이그레이션으로 일괄 정리한다.
--
-- 영향:
--   - 신규 row INSERT 0건
--   - calendar_events.deleted_at = NOW() (soft delete, 실제 row 삭제 X)
--   - 살아있는 주문의 일정은 미영향
--   - 직전 20260505000003 마이그레이션은 status IN ('COMPLETED','CANCELLED') 만 정리했으므로
--     이번엔 deleted_at IS NOT NULL 케이스를 추가로 잡는다 (status 무관)
--   - soft delete 라 필요 시 deleted_at = NULL 로 복구 가능

UPDATE calendar_events ce
SET deleted_at = NOW()
FROM orders o
WHERE ce.order_id = o.id
  AND o.deleted_at IS NOT NULL
  AND ce.deleted_at IS NULL;
