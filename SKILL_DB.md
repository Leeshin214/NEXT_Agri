# SKILL_DB.md — Database Schema Agent

## 역할
Supabase(PostgreSQL) 데이터베이스 스키마 설계, 마이그레이션 파일 생성, RLS 정책 설정을 담당한다.

---

## 반드시 지켜야 할 규칙

### 1. 기본 컬럼 구조
모든 테이블은 아래 컬럼을 반드시 포함한다:
```sql
id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
deleted_at  TIMESTAMPTZ  -- soft delete
```

### 2. updated_at 자동 갱신 트리거
```sql
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
-- 각 테이블에 적용
CREATE TRIGGER set_updated_at BEFORE UPDATE ON {table}
FOR EACH ROW EXECUTE FUNCTION update_updated_at();
```

### 3. RLS 필수 적용
- 모든 테이블에 `ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;`
- 사용자는 자신의 데이터만 접근 가능
- service_role은 모든 접근 허용

### 4. 인덱스
- FK 컬럼 전체에 인덱스 생성
- 자주 검색하는 컬럼 (status, role, created_at) 인덱스 추가
- 복합 인덱스는 쿼리 패턴 기반으로 설계

---

## 스키마 설계

### users 테이블
```sql
CREATE TABLE users (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  supabase_uid  UUID UNIQUE NOT NULL,  -- Supabase Auth UID
  email         TEXT UNIQUE NOT NULL,
  name          TEXT NOT NULL,
  role          TEXT NOT NULL CHECK (role IN ('SELLER', 'BUYER', 'ADMIN')),
  company_name  TEXT,
  phone         TEXT,
  profile_image TEXT,
  is_active     BOOLEAN DEFAULT true,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at    TIMESTAMPTZ
);
```

### products 테이블
```sql
CREATE TABLE products (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  seller_id      UUID NOT NULL REFERENCES users(id),
  name           TEXT NOT NULL,           -- 품목명 (사과, 양파 등)
  category       TEXT NOT NULL CHECK (category IN ('FRUIT', 'VEGETABLE', 'GRAIN', 'OTHER')),
  origin         TEXT,                    -- 원산지
  spec           TEXT,                    -- 규격 (특, 상, 중)
  unit           TEXT NOT NULL CHECK (unit IN ('kg', 'box', 'piece', 'bag')),
  price_per_unit INTEGER NOT NULL,        -- 단가 (원)
  stock_quantity INTEGER NOT NULL DEFAULT 0,
  min_order_qty  INTEGER DEFAULT 1,
  status         TEXT NOT NULL DEFAULT 'NORMAL' 
                   CHECK (status IN ('NORMAL', 'LOW_STOCK', 'OUT_OF_STOCK', 'SCHEDULED')),
  description    TEXT,
  image_url      TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at     TIMESTAMPTZ
);
```

### partners 테이블
```sql
CREATE TABLE partners (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID NOT NULL REFERENCES users(id),  -- 관계의 주체
  partner_user_id UUID NOT NULL REFERENCES users(id),  -- 거래처
  nickname        TEXT,                                 -- 사용자 지정 별칭
  status          TEXT NOT NULL DEFAULT 'ACTIVE' 
                    CHECK (status IN ('ACTIVE', 'INACTIVE', 'PENDING')),
  is_favorite     BOOLEAN DEFAULT false,
  notes           TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(user_id, partner_user_id)
);
```

### orders 테이블
```sql
CREATE TABLE orders (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  order_number        TEXT UNIQUE NOT NULL,   -- ORD-20240315-001
  buyer_id            UUID NOT NULL REFERENCES users(id),
  seller_id           UUID NOT NULL REFERENCES users(id),
  status              TEXT NOT NULL DEFAULT 'QUOTE_REQUESTED'
                        CHECK (status IN (
                          'QUOTE_REQUESTED', 'NEGOTIATING', 'CONFIRMED',
                          'PREPARING', 'SHIPPING', 'COMPLETED', 'CANCELLED'
                        )),
  total_amount        INTEGER,                -- 총 금액 (원)
  delivery_date       DATE,                   -- 납품 희망일
  delivery_address    TEXT,
  notes               TEXT,
  cancellation_reason TEXT,                   -- 취소 사유 (2026-04-27 추가)
  cancelled_at        TIMESTAMPTZ,            -- 취소 시각
  cancelled_by        UUID REFERENCES users(id), -- 취소 주체
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at          TIMESTAMPTZ
);
```

### order_items 테이블
```sql
CREATE TABLE order_items (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  order_id    UUID NOT NULL REFERENCES orders(id),
  product_id  UUID NOT NULL REFERENCES products(id),
  quantity    INTEGER NOT NULL,
  unit_price  INTEGER NOT NULL,           -- 협상 단가
  subtotal    INTEGER NOT NULL,
  notes       TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### calendar_events 테이블
```sql
CREATE TABLE calendar_events (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID NOT NULL REFERENCES users(id),
  order_id    UUID REFERENCES orders(id),
  title       TEXT NOT NULL,
  event_type  TEXT NOT NULL CHECK (event_type IN (
                'SHIPMENT', 'DELIVERY', 'MEETING', 'QUOTE_DEADLINE', 'ORDER', 'OTHER'
              )),
  event_date  DATE NOT NULL,
  start_time  TIME,
  end_time    TIME,
  description TEXT,
  is_allday   BOOLEAN DEFAULT true,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### chat_rooms 테이블
```sql
CREATE TABLE chat_rooms (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  order_id     UUID REFERENCES orders(id),
  seller_id    UUID NOT NULL REFERENCES users(id),
  buyer_id     UUID NOT NULL REFERENCES users(id),
  last_message TEXT,
  last_message_at TIMESTAMPTZ,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### messages 테이블
```sql
CREATE TABLE messages (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  room_id      UUID NOT NULL REFERENCES chat_rooms(id),
  sender_id    UUID NOT NULL REFERENCES users(id),
  content      TEXT NOT NULL,
  is_read      BOOLEAN DEFAULT false,
  -- 주문 협상 ↔ 채팅 양방향 연결 (2026-04-27 추가)
  message_type TEXT NOT NULL DEFAULT 'TEXT'
                CHECK (message_type IN (
                  'TEXT',           -- 일반 사용자 메시지
                  'SYSTEM',         -- 시스템 안내
                  'COUNTER_OFFER',  -- 협상가 제시
                  'OFFER_ACCEPTED', -- 협상가 수락
                  'OFFER_REJECTED', -- 협상가 거절
                  'ORDER_STATUS',   -- 주문 상태 변경 (CONFIRMED/PREPARING/SHIPPING/COMPLETED)
                  'ORDER_CANCELLED' -- 주문 취소
                )),
  metadata     JSONB,            -- 이벤트별 부가 정보 (offer_id, proposed_total_amount, etc.)
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at   TIMESTAMPTZ DEFAULT NULL
);

-- 채팅방의 협상 이벤트만 빠르게 조회용 복합 인덱스
CREATE INDEX idx_messages_room_type ON messages(room_id, message_type);
```

### message metadata 스키마 (message_type 별)
```typescript
// COUNTER_OFFER
{ offer_id: UUID, order_id: UUID, proposed_total_amount: int, from_role: "SELLER"|"BUYER", notes: str?, status: "PENDING" }
// OFFER_ACCEPTED
{ offer_id: UUID, order_id: UUID, accepted_amount: int, accepted_by: UUID }
// OFFER_REJECTED
{ offer_id: UUID, order_id: UUID, rejected_amount: int, rejected_by: UUID }
// ORDER_STATUS
{ order_id: UUID, order_number: str, from_status: str, to_status: str }
// ORDER_CANCELLED
{ order_id: UUID, order_number: str, reason: str, cancelled_by: UUID }
// SYSTEM (견적 요청 알림 등)
{ order_id: UUID, order_number: str, total_amount: int? }
```

### ai_conversations 테이블 (AI 대화 히스토리)
```sql
CREATE TABLE ai_conversations (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      UUID NOT NULL REFERENCES users(id),
  prompt       TEXT NOT NULL,
  response     TEXT NOT NULL,
  prompt_type  TEXT,                      -- 빠른 프롬프트 유형
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### subscriptions / subscription_items 테이블 — 정기배송 V1.5 Phase 1 (2026-04-28)
```sql
-- 정기배송 마스터
CREATE TABLE subscriptions (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  seller_id           UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  buyer_id            UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  partner_id          UUID REFERENCES partners(id) ON DELETE SET NULL,
  frequency           TEXT NOT NULL CHECK (frequency IN ('WEEKLY','BIWEEKLY','MONTHLY')),
  day_of_week         INT  CHECK (day_of_week BETWEEN 0 AND 6),
  day_of_month        INT  CHECK (day_of_month BETWEEN 1 AND 31),
  start_date          DATE NOT NULL,
  end_date            DATE,
  next_delivery_date  DATE NOT NULL,
  status              TEXT NOT NULL DEFAULT 'ACTIVE'
                        CHECK (status IN ('ACTIVE','PAUSED','ENDED','CANCELLED')),
  delivery_address    TEXT,
  notes               TEXT,
  total_amount        INTEGER NOT NULL DEFAULT 0,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at          TIMESTAMPTZ
);

-- 정기배송 라인
CREATE TABLE subscription_items (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  subscription_id UUID NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
  product_id      UUID NOT NULL REFERENCES products(id),
  quantity        INTEGER NOT NULL CHECK (quantity > 0),
  unit_price      INTEGER NOT NULL CHECK (unit_price >= 0),
  unit            TEXT NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- orders 테이블에 추적 컬럼 추가
ALTER TABLE orders
  ADD COLUMN subscription_id UUID REFERENCES subscriptions(id),
  ADD COLUMN subscription_round INT;
```
- 인덱스: `idx_subscriptions_seller/buyer/partner` (deleted_at IS NULL 조건),
  `idx_subscriptions_next_date` (status='ACTIVE' AND deleted_at IS NULL — 배치 검색용),
  `idx_subscription_items_subscription`, `idx_orders_subscription` (deleted_at IS NULL).
- RLS: subscriptions/SELECT/INSERT/UPDATE 3정책 + subscription_items/SELECT/INSERT/UPDATE/DELETE 4정책.
  기존 컨벤션대로 `auth.uid()` ↔ `users.supabase_uid` 매핑 사용.
- `subscription_items` 는 `deleted_at` 컬럼 없음 (부모 subscriptions 의 soft delete + ON DELETE CASCADE 로 간접 관리).
- 마이그레이션 파일: `supabase/migrations/20260428000001_create_subscriptions.sql` (검증된 적용, 2026-04-28).

---

## RLS 정책 예시

### users 테이블
```sql
-- 자신의 데이터만 조회/수정
CREATE POLICY "users_self_access" ON users
  USING (supabase_uid = auth.uid());

-- 거래처로 연결된 다른 사용자 기본 정보 조회 허용
CREATE POLICY "users_partner_read" ON users
  FOR SELECT USING (
    id IN (
      SELECT partner_user_id FROM partners WHERE user_id IN (
        SELECT id FROM users WHERE supabase_uid = auth.uid()
      )
    )
  );
```

### products 테이블
```sql
-- 판매자: 자신의 상품 전체 접근
CREATE POLICY "products_seller_access" ON products
  USING (seller_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid()));

-- 구매자: 공개 상품 조회
CREATE POLICY "products_buyer_read" ON products
  FOR SELECT USING (status != 'OUT_OF_STOCK' AND deleted_at IS NULL);
```

### orders 테이블
```sql
-- 주문 당사자만 접근
CREATE POLICY "orders_participant_access" ON orders
  USING (
    buyer_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
    OR
    seller_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
  );
```

### messages 테이블
```sql
-- 채팅방 참여자만 메시지 접근
CREATE POLICY "messages_room_access" ON messages
  USING (
    room_id IN (
      SELECT id FROM chat_rooms
      WHERE seller_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
         OR buyer_id  IN (SELECT id FROM users WHERE supabase_uid = auth.uid())
    )
  );
```

---

## 마이그레이션 파일 생성 규칙

```
supabase/migrations/
  YYYYMMDDHHMMSS_create_users.sql
  YYYYMMDDHHMMSS_create_products.sql
  YYYYMMDDHHMMSS_create_partners.sql
  YYYYMMDDHHMMSS_create_orders.sql
  YYYYMMDDHHMMSS_create_calendar_events.sql
  YYYYMMDDHHMMSS_create_chat.sql
  YYYYMMDDHHMMSS_create_ai_conversations.sql
  YYYYMMDDHHMMSS_add_rls_policies.sql
  YYYYMMDDHHMMSS_add_indexes.sql
```

---

## Seed 데이터 구조

```sql
-- supabase/seed.sql
-- 테스트용 사용자 (Supabase Auth에서 수동 생성 후 UUID 매핑)
INSERT INTO users (supabase_uid, email, name, role, company_name, phone) VALUES
  ('...', 'seller1@test.com', '김철수', 'SELLER', '행복농산', '010-1234-5678'),
  ('...', 'seller2@test.com', '이영희', 'SELLER', '서울청과', '010-2345-6789'),
  ('...', 'buyer1@test.com',  '박민준', 'BUYER',  'A마트',   '010-3456-7890'),
  ('...', 'buyer2@test.com',  '최지수', 'BUYER',  '강남식자재', '010-4567-8901');

-- 상품 샘플
INSERT INTO products (seller_id, name, category, origin, spec, unit, price_per_unit, stock_quantity, status) VALUES
  (..., '사과', 'FRUIT',     '경북 청송', '특', 'box', 45000, 120, 'NORMAL'),
  (..., '양파', 'VEGETABLE', '전남 무안', '상', 'kg',   800,  500, 'NORMAL'),
  (..., '감자', 'VEGETABLE', '강원 평창', '상', 'kg',  1200,   30, 'LOW_STOCK'),
  (..., '딸기', 'FRUIT',     '경남 진주', '특', 'box', 38000,   0, 'OUT_OF_STOCK'),
  (..., '쌀',   'GRAIN',     '전북 익산', '일반', 'bag', 52000, 200, 'NORMAL');
```

---

## 작업 체크리스트

- [ ] 모든 테이블 생성 SQL 작성
- [ ] updated_at 트리거 모든 테이블 적용
- [ ] RLS Enable + 정책 작성
- [ ] 인덱스 생성 (FK, status, created_at)
- [ ] Seed 데이터 작성
- [ ] 마이그레이션 파일 순서 확인
- [ ] `supabase db push` 실행 검증

---

## 실전 발견 사항

> **agent 전용 기록 공간**: 실제 작업을 통해 검증된 패턴과 함정만 기록한다.
> 가설이나 일반적인 PostgreSQL 지식은 추가하지 않는다.

### 검증된 패턴

- **운영 DB 정합 — soft delete 컬럼 보유 테이블 (2026-04-27 마이그레이션 후 최신)**: 운영 Supabase 기준으로 `deleted_at` 컬럼이 존재하는 테이블은 `users, products, partners, orders, calendar_events, messages` 6개. `deleted_at` 이 없는 테이블은 `order_items, chat_rooms, ai_conversations` 3개. 모든 soft-delete 지원 테이블에 대해 조회 쿼리는 `.is_("deleted_at", None)` 필터, 삭제 액션은 `UPDATE … SET deleted_at = NOW()` 패턴을 사용한다.

- **calendar_events deleted_at 추가됨 (2026-04-27)**: 이전에 `calendar_events` 는 `deleted_at` 컬럼이 없어서 필터를 생략했으나, 마이그레이션으로 추가됨. 이제 `agent_tools.get_calendar_events` 의 `.is_("deleted_at", None)` 필터가 정상 동작한다. INSERT 시에는 컬럼을 명시하지 않으면 NULL default 가 들어간다.

- **calendar_events ↔ orders ↔ order_items ↔ products 3-depth 임베딩 응답 (2026-04-27)**: 캘린더 일정 카드에 주문 번호와 상품명을 함께 표기하기 위해 응답 시 PostgREST 임베딩으로 join 한다. 별도 컬럼 추가/마이그레이션 불필요 — 응답 단계에서만 파생 필드로 노출. 임베딩 트리:
  ```
  calendar_events.* + 
    order:orders!order_id(
      order_number, deleted_at,
      items:order_items(
        product:products(name, deleted_at)
      )
    )
  ```
  - `orders!order_id` — column-alias FK embedding (FK 이름 자동 추론)
  - 한 주문에 여러 상품이 있으면 첫 활성 상품명을 메인으로, 나머지는 "외 N건" 형태로 카운트.
  - `orders.deleted_at` / `products.deleted_at` 는 임베딩이 자동 필터하지 않으므로 응답 flatten 단계에서 명시 검사 필요.

- **products.unit / category CHECK 제약 확장 (2026-04-27)**: 운영 DB에 적용된 CHECK 제약은 unit 13종(`kg, box, piece, bag, 개, 포대, 묶음, g, L, ml, 판, 줄, 세트`), category 13종, status 4종(`NORMAL, LOW_STOCK, OUT_OF_STOCK, SCHEDULED`). LLM 안내 프롬프트와 동기화 상태 유지 필요.

- **BUYER의 주문 상품 조회 패턴**: 구매자가 최근 주문한 상품 목록을 가져올 때 직접 JOIN이 없으므로 3단계로 나눠 조회한다. orders(buyer_id) → order_items(order_id) → products(id). 각 단계를 별도 `asyncio.to_thread` 호출로 처리하고 product_ids는 set으로 중복 제거 후 `.in_()` 필터를 사용한다.

- **soft delete 서비스 통일 패턴 (검증됨)**: `delete_*` 서비스 메서드는 모든 테이블에서 동일한 형태를 따른다. 권한 검증을 위한 `eq("user_id"|"seller_id", ...)` 와 멱등성을 위한 `.is_("deleted_at", None)` 을 함께 사용한다. 시그니처는 `(resource_id, owner_id) -> bool` 로 통일.
  ```python
  async def delete_partner(self, partner_id: UUID, user_id: UUID) -> bool:
      deleted_at = datetime.now(timezone.utc).isoformat()
      result = await asyncio.to_thread(
          lambda: self.table.update({"deleted_at": deleted_at})
          .eq("id", str(partner_id))
          .eq("user_id", str(user_id))   # 권한 — 본인 데이터만
          .is_("deleted_at", None)        # 이미 삭제된 행 제외 (멱등성)
          .execute()
      )
      return bool(result.data)
  ```
  - `update_*` 메서드도 동일하게 `.is_("deleted_at", None)` 추가하여 삭제된 행 수정을 차단한다.
  - `list_*` 메서드도 `.is_("deleted_at", None)` 필터를 select 체인 첫 단계에 추가한다.

### 주의사항 & 함정

- **deleted_at 컬럼 없는 테이블에 필터 적용 금지**: `order_items, chat_rooms, ai_conversations` 3개 테이블은 운영 DB에 `deleted_at` 컬럼이 없다. `.is_("deleted_at", None)` 적용 시 PostgREST 가 `column does not exist` 오류를 던진다. order_items 는 부모 orders 의 soft delete 로 간접 차단된다.

- **JSONB 부분 업데이트용 SECURITY DEFINER 함수 (검증됨, 2026-04-27)**: `messages.metadata` 같은 JSONB 컬럼의 특정 키만 갱신해야 할 때, `jsonb_set()` 을 호출하는 RPC 함수를 마이그레이션으로 등록하면 한 번의 UPDATE 로 처리된다. fetch → mutate → update 패턴 (3 round-trip) 보다 훨씬 빠르고 race-free. SECURITY DEFINER 로 작성해 service_role 호출 시 RLS 우회.
  ```sql
  -- migration: 20260427000005_sync_offer_status_fn.sql
  CREATE OR REPLACE FUNCTION sync_offer_status_in_messages(
    p_offer_id UUID, p_new_status TEXT
  ) RETURNS INTEGER LANGUAGE plpgsql SECURITY DEFINER
  SET search_path = public AS $$
  DECLARE v_count INTEGER;
  BEGIN
    UPDATE messages
    SET metadata = jsonb_set(metadata, '{status}', to_jsonb(p_new_status), true)
    WHERE (metadata->>'offer_id')::uuid = p_offer_id
      AND metadata IS NOT NULL;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
  END;
  $$;
  ```
  - `jsonb_set(meta, '{status}', to_jsonb(...), true)` 4번째 arg `true` = create_missing 키도 추가
  - PostgREST RPC 호출: `client.rpc("fn_name", {"p_offer_id": "...", "p_new_status": "..."}).execute()`
  - 운영 권장: RPC 우선 시도 + 실패 시 fetch/update fallback. 검증된 적용처: `order_service._sync_offer_status_in_messages`.

- **PostgREST `eq("metadata->>key", value)` 캐시/지연 함정 (2026-04-27 검증)**: PostgREST 의 JSONB path 추출 필터 `eq("metadata->>offer_id", "...")` 는 INSERT/UPDATE 직후 같은 supabase 클라이언트 인스턴스에서 호출하면 빈 결과를 반환할 수 있다 (replication / 내부 캐시 영향). E2E 검증에서는 같은 트랜잭션 직후 검증보다는 `message_type` 등 정적 컬럼으로 가져온 뒤 client-side 에서 `metadata.offer_id` 비교하는 것이 안정적. 운영 코드 자체는 RPC 함수가 직접 SQL UPDATE 를 수행하므로 문제 없음 — 검증/조회 측에서만 주의.

- **calendar_events `(order_id, user_id, event_date)` partial unique index — 한 주문×한 user 당 active 1개 보장 (2026-04-27 중복 누적 버그 수정)**: order-linked 캘린더 일정에 UNIQUE 제약이 없어 race condition 또는 과거 backfill 폭주 시기에 같은 (order_id, user_id, event_date) active row 가 수십 개 누적되는 정합성 버그가 발생. `order_service._sync_calendar_events_for_order_sync` 가 일부 정리 로직을 갖고 있었지만 race 에 취약했고, 납기일 변경 시 옛 event_date 의 row 가 잔존하는 케이스도 있었다. DB 차원 보장이 필요.

  ```sql
  -- migration: 20260427000006_cleanup_duplicate_calendar_events.sql

  -- A) 그룹별로 가장 최신 active row 1개만 남기고 나머지 soft-delete
  WITH ranked AS (
    SELECT id,
      ROW_NUMBER() OVER (
        PARTITION BY order_id, user_id, event_date
        ORDER BY updated_at DESC, created_at DESC, id
      ) AS rn
    FROM calendar_events
    WHERE deleted_at IS NULL AND order_id IS NOT NULL
  )
  UPDATE calendar_events SET deleted_at = NOW(), updated_at = NOW()
  WHERE id IN (SELECT id FROM ranked WHERE rn > 1);

  -- B) 주문이 CANCELLED/soft-deleted 인데 calendar_events 가 active 인 row 정리
  UPDATE calendar_events ce
  SET deleted_at = NOW(), updated_at = NOW()
  FROM orders o
  WHERE ce.order_id = o.id AND ce.deleted_at IS NULL
    AND (o.status = 'CANCELLED' OR o.deleted_at IS NOT NULL);

  -- C) 주문 delivery_date 와 다른 event_date 의 잔존 active row 정리
  UPDATE calendar_events ce
  SET deleted_at = NOW(), updated_at = NOW()
  FROM orders o
  WHERE ce.order_id = o.id AND ce.deleted_at IS NULL
    AND o.deleted_at IS NULL AND o.status <> 'CANCELLED'
    AND o.delivery_date IS NOT NULL
    AND ce.event_date <> o.delivery_date;

  -- D) 향후 재발 방지 — partial unique index
  CREATE UNIQUE INDEX IF NOT EXISTS uniq_calendar_events_active_order_user_date
    ON calendar_events (order_id, user_id, event_date)
    WHERE order_id IS NOT NULL AND deleted_at IS NULL;
  ```
  - manual event (`order_id IS NULL`) 은 partial index 에서 제외 → 자유롭게 추가 가능.
  - soft-deleted row 도 인덱스에서 제외 → soft-delete 후 재추가 가능.
  - 실제 cleanup 마이그레이션은 항상 D) partial index 생성 직전에 A/B/C 로 활성 중복을 정리해야 INDEX 생성이 충돌 없이 성공한다 (PostgreSQL 은 partial index 생성 시점에 기존 데이터 무결성 검사).
  - 동일 패턴이 적용된 사례: `partners (user_id, partner_user_id) WHERE deleted_at IS NULL` (2026-04-27).

- **partners.status — V1 즐겨찾기 모델 (Option A): 등록 즉시 ACTIVE 고정 (2026-04-27)**: `partners` 테이블 status 컬럼의 SQL DEFAULT 는 `'ACTIVE'` (`20260321000003_create_partners.sql`) 이며, V1 에서는 양방향 승인(PENDING → ACTIVE) 플로우를 구현하지 않고 즐겨찾기 모델로 단순화한다. `partner_service.create_partner` 는 INSERT payload 에 `"status": "ACTIVE"` 를 명시적으로 박아 전달한다 (DB default 와 동일하지만, 미래에 default 가 바뀌어도 V1 정책이 깨지지 않도록 방어). `PartnerCreate` schema 는 `status` 필드를 받지 않아 클라이언트가 PENDING 으로 등록할 수 없다. 단, PATCH `/partners/{id}` 는 `PartnerUpdate.status: Optional[str]` 로 사용자가 직접 INACTIVE 등으로 전이 가능 — 이는 즐겨찾기 해제/거래 종료 의미. 추후 양방향 승인 모델 도입 시 `PartnerStatus` enum 의 `PENDING` 을 그대로 재사용할 수 있도록 enum 자체는 유지(`ACTIVE`/`INACTIVE`/`PENDING` 3종 보존).

- **subscriptions / subscription_items 정합성 — RLS 컨벤션 통일 (2026-04-28)**: 새 마이그레이션의 RLS 정책은 반드시 기존 프로젝트 컨벤션 `id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())` 패턴을 따라야 한다. 외부 명세에 `auth.uid() = buyer_id` 형태가 있더라도 그대로 적용하면 안 된다 — Supabase Auth 의 `auth.uid()` 는 `users.supabase_uid` 이지 `users.id` 가 아니므로 비교가 항상 false 가 되어 모든 SELECT/INSERT/UPDATE 가 차단된다. 백엔드가 service_role 키로 접근하므로 RLS 우회되어 평소엔 문제 없지만, 미래에 anon 키 직접 접근 / Edge Functions / Realtime subscribe 시점에 폭발한다. 적용 위치:
  - `subscriptions_participant_select/insert/update`
  - `subscription_items_participant_select/insert/update/delete`

- **soft delete 컬럼 보유 테이블 갱신 (2026-04-28 마이그레이션 후)**: 운영 Supabase 기준 `deleted_at` 컬럼 보유 테이블 = `users, products, partners, orders, calendar_events, messages, subscriptions` (7개). `deleted_at` 미보유 = `order_items, chat_rooms, ai_conversations, subscription_items, negotiation_history`. subscription_items 는 부모 subscriptions 의 soft delete + ON DELETE CASCADE FK 로 간접 관리되어 자체 deleted_at 컬럼 불필요.

- **subscriptions.next_delivery_date 계산 정책 (2026-04-28)**: 첫 회차의 `next_delivery_date` 는 `start_date` 와 동일하게 시작 (즉 최초 INSERT 시점에 `next_delivery_date = start_date`). `generate_order_for_round` 호출 시 주문 생성 후 `compute_next_date` 로 다음 회차 갱신. PAUSED → ACTIVE 전환 시 `update_subscription` 안에서 오늘 이후가 될 때까지 `compute_next_date` 를 반복 호출해 재계산 (max 520회 = 약 10년치 주간 회차로 무한 루프 차단). MONTHLY 의 1/31 → 2/28 clamp 도 `calendar.monthrange()` 로 처리 — 검증 완료.
