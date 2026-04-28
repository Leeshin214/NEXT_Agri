-- ===========================================
-- sync_offer_status_in_messages — 협상 메시지 metadata.status 동기화 함수
-- ===========================================
-- 협상가(offer)의 라이프사이클(ACCEPTED/REJECTED/SUPERSEDED)이 negotiation_history 에서 변경될 때,
-- 같은 offer_id 를 metadata 에 가진 messages 행들의 metadata.status 도 함께 갱신해야
-- 프론트가 stale 한 PENDING 카드(수락/거절 버튼 노출)를 표시하지 않는다.
--
-- 정책:
--   - service_role (백엔드) 에서 호출 — RLS 우회
--   - jsonb_set 으로 status 키만 부분 업데이트 (다른 metadata 키 보존)
--   - metadata 가 NULL 인 행은 영향 없음 (jsonb_set 이 NULL 입력에 NULL 반환)

CREATE OR REPLACE FUNCTION sync_offer_status_in_messages(
  p_offer_id UUID,
  p_new_status TEXT
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_updated_count INTEGER;
BEGIN
  UPDATE messages
  SET metadata = jsonb_set(metadata, '{status}', to_jsonb(p_new_status), true)
  WHERE (metadata->>'offer_id')::uuid = p_offer_id
    AND metadata IS NOT NULL;

  GET DIAGNOSTICS v_updated_count = ROW_COUNT;
  RETURN v_updated_count;
END;
$$;

COMMENT ON FUNCTION sync_offer_status_in_messages(UUID, TEXT) IS
  '협상가 메시지(messages.metadata.status) 동기화. order_service 에서 ACCEPTED/REJECTED/SUPERSEDED 처리 시 호출.';
