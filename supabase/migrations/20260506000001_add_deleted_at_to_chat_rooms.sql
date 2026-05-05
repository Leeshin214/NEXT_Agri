-- chat_rooms.deleted_at 컬럼 추가 — 주문 취소 시 채팅방 soft-delete 지원 (2026-05-06)
--
-- 배경:
--   주문이 취소되면 연결된 채팅방도 목록에서 사라져야 한다.
--   기존에는 chat_rooms 에 deleted_at 컬럼이 없어 hard-delete 또는 방치만 가능했다.
--   이력 보존을 위해 soft-delete 컬럼을 추가하고, list/조회 쿼리에 필터를 적용한다.
--
-- 영향:
--   - 신규 INSERT 는 NULL default 가 들어감 → 기존 동작 영향 없음.
--   - SKILL_CHAT.md / SKILL_DB.md 의 "chat_rooms 에 deleted_at 컬럼 없음" 함정 항목은
--     이 마이그레이션 이후로 무효 — 두 SKILL 파일에서 정정 필요.

ALTER TABLE chat_rooms ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ DEFAULT NULL;
