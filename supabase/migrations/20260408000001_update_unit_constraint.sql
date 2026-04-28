-- products.unit CHECK 제약 확장
-- orchestrator.py / agent_tools.py 가 LLM에 안내하는 13종 단위 모두 허용
-- 기존 'kg', 'box', 'piece', 'bag' 데이터는 새 제약에도 포함되어 데이터 영향 없음

ALTER TABLE products DROP CONSTRAINT IF EXISTS products_unit_check;

ALTER TABLE products ADD CONSTRAINT products_unit_check
  CHECK (unit IN (
    'kg', 'box', 'piece', 'bag',
    '개', '포대', '묶음',
    'g', 'L', 'ml',
    '판', '줄', '세트'
  ));
