-- 이미 완료(COMPLETED) / 취소(CANCELLED) 된 주문의 살아있는 calendar_events 를 일괄 soft delete
--
-- 배경:
--   order_service._sync_calendar_events_for_order_sync 가 이전엔 status == CANCELLED 만
--   체크해서 COMPLETED 주문의 캘린더 일정이 자동 삭제되지 않았음.
--   코드는 35f112a 에서 TERMINAL_ORDER_STATUSES = {COMPLETED, CANCELLED} 로 보강됐고,
--   이 마이그레이션은 그 시점 이전에 살아있는 일정을 일괄 정리한다.
--
-- 영향:
--   - 신규 row INSERT 0건
--   - calendar_events.deleted_at = NOW() 로 soft delete (실제 row 삭제 X)
--   - 진행 중 주문 (QUOTE_REQUESTED/NEGOTIATING/CONFIRMED/PREPARING/SHIPPING) 의 일정은 미영향
--   - soft delete 라 필요 시 deleted_at = NULL 로 복구 가능

UPDATE calendar_events ce
SET deleted_at = NOW()
FROM orders o
WHERE ce.order_id = o.id
  AND o.status IN ('COMPLETED', 'CANCELLED')
  AND ce.deleted_at IS NULL;
