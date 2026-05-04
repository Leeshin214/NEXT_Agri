-- ai_conversations 에 tool_context 컬럼 추가
-- 에이전트가 한 턴에서 호출한 tool 결과(seller_id/product_id 등 UUID 포함)를 저장해
-- 다음 턴에서 히스토리로 주입함으로써 LLM이 직전 조회 UUID를 재활용할 수 있게 한다.
ALTER TABLE ai_conversations
  ADD COLUMN IF NOT EXISTS tool_context JSONB;
