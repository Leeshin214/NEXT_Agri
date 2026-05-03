-- ===========================================
-- buyer_inventories — 구매자(BUYER) 재고 관리 테이블 (옵션 A 신설)
-- ===========================================
-- 설계 배경:
--   판매자(SELLER) 의 재고는 products.stock_quantity 에서 관리되고
--   주문 CONFIRMED 시점에 차감(_deduct_seller_stock_for_order)된다.
--   구매자는 자기 창고/매장에 들어온 농산물을 별도로 추적할 수단이 없어
--   본 테이블을 신설한다.
--
-- 자동 누적:
--   order_service.update_status() 안에서 new_status='COMPLETED' 진입 시
--   _add_buyer_inventory_for_order(order_id) 가 호출되어
--   해당 주문의 order_items 를 buyer_id 별로 합산하여 UPSERT 한다.
--   멱등성은 orders.inventory_added_at 컬럼으로 보장 (이미 추가된 주문은 skip).
--
-- API:
--   GET    /buyer/inventory          — 본인 재고 목록 (검색 / product_id 필터 / 페이지)
--   GET    /buyer/inventory/{id}     — 단건 상세
--   PATCH  /buyer/inventory/{id}     — 수량/메모 수동 조정 (소진 처리 등)
--   DELETE /buyer/inventory/{id}     — soft delete (목록에서 숨김)
--   POST 는 없음 — 모든 row 는 주문 완료 시 자동 생성된다.

-- ===========================================
-- 1) buyer_inventories 테이블
-- ===========================================
CREATE TABLE IF NOT EXISTS buyer_inventories (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  buyer_id        UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  product_id      UUID NOT NULL REFERENCES products(id),
  quantity        INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
  unit            TEXT,
  last_added_at   TIMESTAMPTZ,
  notes           TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at      TIMESTAMPTZ
);

-- updated_at 자동 갱신 트리거 (전역 함수 update_updated_at 재사용)
CREATE TRIGGER set_updated_at BEFORE UPDATE ON buyer_inventories
FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ===========================================
-- 2) UNIQUE 제약 — 활성 행 한정 (NULLS NOT DISTINCT 패턴)
-- ===========================================
-- 한 buyer 의 한 product 당 active 행이 정확히 1개 존재하도록 보장.
-- soft-deleted 행은 인덱스에서 제외 (partial WHERE) 되어
-- 사용자가 hide → 다시 자동 누적 → 새 active 행 생성이 정상 동작한다.
-- (subscriptions / partners 의 partial unique 패턴과 동일)
CREATE UNIQUE INDEX IF NOT EXISTS uniq_buyer_inventories_active_buyer_product
  ON buyer_inventories (buyer_id, product_id)
  WHERE deleted_at IS NULL;

-- ===========================================
-- 3) 조회 인덱스 (모두 partial — soft-delete 제외)
-- ===========================================
-- a) buyer_id 별 목록 조회 — 가장 자주 쓰이는 패턴
CREATE INDEX IF NOT EXISTS idx_buyer_inventories_buyer
  ON buyer_inventories (buyer_id)
  WHERE deleted_at IS NULL;

-- b) product_id 별 — 같은 상품을 갖고 있는 buyer 검색용 (어드민/통계)
CREATE INDEX IF NOT EXISTS idx_buyer_inventories_product
  ON buyer_inventories (product_id)
  WHERE deleted_at IS NULL;

-- c) 최근 입고순 정렬 — last_added_at DESC 로 빠른 정렬
CREATE INDEX IF NOT EXISTS idx_buyer_inventories_recent_added
  ON buyer_inventories (buyer_id, last_added_at DESC NULLS LAST)
  WHERE deleted_at IS NULL;

-- ===========================================
-- 4) RLS (subscriptions / partners 컨벤션 — auth.uid() ↔ users.supabase_uid)
-- ===========================================
-- 백엔드는 service_role 키로 우회 접근하지만,
-- anon/authenticated 키로 직접 접근하는 미래 시나리오를 위해 정책 작성.
-- INSERT 정책 미정의 → 클라이언트가 직접 INSERT 불가 (자동 누적 + service_role 만)
-- DELETE 도 정책 미정의 → 클라이언트는 PATCH(soft delete) 만 가능
ALTER TABLE buyer_inventories ENABLE ROW LEVEL SECURITY;

-- SELECT: 본인 재고만
CREATE POLICY "buyer_inventories_select_own" ON buyer_inventories
  FOR SELECT USING (
    buyer_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
  );

-- UPDATE: 본인 재고만 (수량 조정 / soft delete)
CREATE POLICY "buyer_inventories_update_own" ON buyer_inventories
  FOR UPDATE USING (
    buyer_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
  );


-- ===========================================
-- 5) orders 테이블 — buyer 재고 누적 멱등성 컬럼
-- ===========================================
-- 같은 주문이 여러 번 COMPLETED 트랜잭션을 거쳐도 buyer_inventories 가
-- 중복 누적되지 않도록 "이미 누적했다"는 시각을 기록.
-- _deduct_seller_stock_for_order 의 inventory_deducted_at 과 동일한 패턴.
ALTER TABLE orders
  ADD COLUMN IF NOT EXISTS inventory_added_at TIMESTAMPTZ;
