-- calendar_events 테이블 soft-delete 컬럼 보강
-- 마이그레이션 20260322000001 이 schema_migrations 에는 적용된 것으로 기록됐으나
-- 실제 운영 DB calendar_events 에 deleted_at 컬럼이 누락되어 다음 코드 경로가 모두 실패 중:
--   - agent_tools.get_calendar_events
--   - calendar_service.list_events / delete_event
--   - schedule_agent.build_schedule_context
-- 코드는 .is_("deleted_at", None) 패턴으로 soft-delete 행을 필터링한다.

ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
