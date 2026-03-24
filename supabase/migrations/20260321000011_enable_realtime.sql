-- Supabase Realtime 활성화: messages, chat_rooms 테이블
-- 메시지 INSERT 이벤트와 채팅방 UPDATE 이벤트를 실시간으로 구독 가능하게 함

ALTER PUBLICATION supabase_realtime ADD TABLE messages;
ALTER PUBLICATION supabase_realtime ADD TABLE chat_rooms;
