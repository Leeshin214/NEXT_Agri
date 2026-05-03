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
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID NOT NULL REFERENCES users(id),
  order_id        UUID REFERENCES orders(id),
  -- 정기배송 자동 등록 일정 식별 (2026-04-28 추가, 마이그레이션 20260428000003)
  subscription_id UUID REFERENCES subscriptions(id) ON DELETE SET NULL,
  title           TEXT NOT NULL,
  event_type      TEXT NOT NULL CHECK (event_type IN (
                    'SHIPMENT', 'DELIVERY', 'MEETING', 'QUOTE_DEADLINE', 'ORDER', 'OTHER'
                  )),
  event_date      DATE NOT NULL,
  start_time      TIME,
  end_time        TIME,
  description     TEXT,
  is_allday       BOOLEAN DEFAULT true,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at      TIMESTAMPTZ
);
-- 정기배송-유저-날짜 활성 행 1개 보장
CREATE UNIQUE INDEX uniq_calendar_events_active_subscription_user_date
  ON calendar_events (subscription_id, user_id, event_date)
  WHERE subscription_id IS NOT NULL AND deleted_at IS NULL;
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

### notifications 테이블 — 우상단 종 아이콘 알림 (2026-04-29)
```sql
CREATE TABLE notifications (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  type       TEXT NOT NULL CHECK (type IN (
                'NEW_MESSAGE',
                'COUNTER_OFFER', 'OFFER_ACCEPTED', 'OFFER_REJECTED',
                'DELIVERY_DATE_CHANGE', 'DELIVERY_DATE_ACCEPTED', 'DELIVERY_DATE_REJECTED',
                'ORDER_STATUS')),
  title      TEXT NOT NULL,
  body       TEXT NOT NULL,
  link_url   TEXT,
  order_id   UUID REFERENCES orders(id)     ON DELETE SET NULL,
  room_id    UUID REFERENCES chat_rooms(id) ON DELETE SET NULL,
  is_read    BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  read_at    TIMESTAMPTZ
);
CREATE INDEX idx_notifications_user_unread
  ON notifications(user_id, created_at DESC) WHERE is_read = false;
CREATE INDEX idx_notifications_user_recent
  ON notifications(user_id, created_at DESC);
```
- RLS: SELECT/UPDATE 본인만 (`user_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())`).
  INSERT 정책 없음 → service_role 만 INSERT (서버 emit 전용).
- Supabase Realtime publication 등록 (`ALTER PUBLICATION supabase_realtime ADD TABLE notifications;`).
- 마이그레이션: `supabase/migrations/20260429000002_create_notifications.sql`.
- `deleted_at` 미보유 — 일반적으로 알림은 일시 보존 (TTL 정책 추가 시 별도 처리).

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

- **partners 양방향 동기화 — create/accept/reject/delete 모두 두 row 처리 (V1.6, 2026-04-28 delete 버그 수정)**: V1.6 양방향 승인 모델에서는 거래 관계 1건 = 본인 row(`user_id=A, partner_user_id=B`) + 반대편 row(`user_id=B, partner_user_id=A`) 두 row 가 항상 짝으로 존재한다. 이 때문에 status/soft-delete 를 변경하는 모든 서비스 메서드는 양쪽을 함께 처리해야 한다. 단방향만 처리하면 상대방 거래처 목록에서 비대칭 상태로 보이는 정합성 버그가 발생한다 (예: 본인은 삭제했는데 상대 화면에선 ACTIVE 로 계속 보임).
  ```python
  # _find_counterpart_row 헬퍼 — partner_service.py
  async def _find_counterpart_row(self, *, my_user_id: str, partner_user_id: str) -> Optional[dict]:
      result = await asyncio.to_thread(
          lambda: self.table.select("*")
          .eq("user_id", partner_user_id)        # 반대편의 user_id = 본인의 partner_user_id
          .eq("partner_user_id", my_user_id)     # 반대편의 partner_user_id = 본인의 user_id
          .is_("deleted_at", None)
          .limit(1).execute()
      )
      return result.data[0] if result.data else None

  # delete_partner — 본인 + 반대편 모두 soft-delete (호출 시그니처는 키워드)
  counterpart = await self._find_counterpart_row(
      my_user_id=user_id_str,
      partner_user_id=partner_user_id_str,
  )
  ```
  - 호출 시그니처는 항상 키워드 인자(`my_user_id=`, `partner_user_id=`) — `accept_partner` / `reject_partner` / `delete_partner` 모두 동일.
  - 본인 row 처리는 strict (없으면 404), 반대편 row 처리는 best-effort (try/except + 로그) — 마이그레이션 전 단방향 데이터나 이미 정리된 row 가 있을 수 있음.
  - 멱등성: 본인 row 조회/UPDATE 모두 `.is_("deleted_at", None)` 필터를 거치므로 같은 partner_id 로 두 번째 호출하면 404 반환. 반대편도 마찬가지로 두 번째 호출에서는 `_find_counterpart_row` 가 None 을 반환해 자동 스킵.
  - return 타입은 기존과 동일 (`bool` for delete, `dict` for accept, `bool` for reject) → router 코드 변경 없음.

- **subscriptions / subscription_items 정합성 — RLS 컨벤션 통일 (2026-04-28)**: 새 마이그레이션의 RLS 정책은 반드시 기존 프로젝트 컨벤션 `id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())` 패턴을 따라야 한다. 외부 명세에 `auth.uid() = buyer_id` 형태가 있더라도 그대로 적용하면 안 된다 — Supabase Auth 의 `auth.uid()` 는 `users.supabase_uid` 이지 `users.id` 가 아니므로 비교가 항상 false 가 되어 모든 SELECT/INSERT/UPDATE 가 차단된다. 백엔드가 service_role 키로 접근하므로 RLS 우회되어 평소엔 문제 없지만, 미래에 anon 키 직접 접근 / Edge Functions / Realtime subscribe 시점에 폭발한다. 적용 위치:
  - `subscriptions_participant_select/insert/update`
  - `subscription_items_participant_select/insert/update/delete`

- **soft delete 컬럼 보유 테이블 갱신 (2026-04-28 마이그레이션 후)**: 운영 Supabase 기준 `deleted_at` 컬럼 보유 테이블 = `users, products, partners, orders, calendar_events, messages, subscriptions` (7개). `deleted_at` 미보유 = `order_items, chat_rooms, ai_conversations, subscription_items, negotiation_history`. subscription_items 는 부모 subscriptions 의 soft delete + ON DELETE CASCADE FK 로 간접 관리되어 자체 deleted_at 컬럼 불필요.

- **subscriptions.next_delivery_date 계산 정책 (2026-04-28)**: 첫 회차의 `next_delivery_date` 는 `start_date` 와 동일하게 시작 (즉 최초 INSERT 시점에 `next_delivery_date = start_date`). `generate_order_for_round` 호출 시 주문 생성 후 `compute_next_date` 로 다음 회차 갱신. PAUSED → ACTIVE 전환 시 `update_subscription` 안에서 오늘 이후가 될 때까지 `compute_next_date` 를 반복 호출해 재계산 (max 520회 = 약 10년치 주간 회차로 무한 루프 차단). MONTHLY 의 1/31 → 2/28 clamp 도 `calendar.monthrange()` 로 처리 — 검증 완료.

- **calendar_events ↔ subscriptions 자동 동기화 (2026-04-28, 마이그레이션 20260428000003)**: 정기배송 등록·수락 시 첫 배송일이 양 당사자 캘린더에 자동 등록되도록 `calendar_events.subscription_id UUID REFERENCES subscriptions(id) ON DELETE SET NULL` 컬럼 추가. 한 정기배송 = 양 당사자 각 1건씩 두 row (seller=`SHIPMENT`, buyer=`DELIVERY`, `order_id IS NULL`). 멱등성 보장은 partial unique index `uniq_calendar_events_active_subscription_user_date ON (subscription_id, user_id, event_date) WHERE subscription_id IS NOT NULL AND deleted_at IS NULL` 로 처리. 기존 `uniq_calendar_events_active_order_user_date` 는 `WHERE order_id IS NOT NULL` 조건이라 두 인덱스가 독립적으로 공존한다.
  - **호출 시점**: `subscription_service.accept_subscription` (PENDING→ACTIVE INSERT), `update_subscription` (frequency/next_delivery_date 변경 시 UPDATE; CANCELLED/ENDED/PAUSED/REJECTED 시 cleanup), `delete_subscription` (미래 일정 cleanup), `generate_order_for_round` (다음 회차로 UPSERT — 회차 주문 자체의 order-linked 일정은 별도로 INSERT 됨).
  - **상태별 동작**: `status='ACTIVE'` 만 캘린더 INSERT/UPDATE. `PENDING`/`PAUSED`/`CANCELLED`/`ENDED`/`REJECTED` 는 `_cleanup_subscription_future_events` 로 미래 일정만 soft-delete (event_date >= today; 이미 회차 주문이 생성된 과거 일정은 이력 보존).
  - **백필 미수행**: 마이그레이션 20260428000003 은 컬럼/인덱스만 추가하고 기존 ACTIVE 정기배송에 대한 backfill 은 수행하지 않는다. 신규 mutation 부터만 동기화. 운영 데이터 양이 적고 사용자 수동 등록 일정과 중복 가능성 때문 — 필요 시 별도 운영 스크립트로 후처리.
  - **응답 스키마**: `CalendarEventResponse.subscription_id: Optional[UUID]` 필드를 추가해 프론트가 정기배송 일정과 일반 일정을 구분할 수 있도록 노출.

- **PostgREST 다건 양방향 N+1 회피 — IN 절 + 메모리 그룹핑 (2026-04-28, PartnerResponse.last_trade_*)**: `partners` 목록 응답에 거래처별 "최근 거래 1건" 을 붙일 때, partner 마다 orders 를 1번씩 조회하면 N+1. PostgREST 는 `DISTINCT ON` 을 지원하지 않으므로 다음 패턴이 검증된 최선책:
  ```python
  # 1) counterpart_ids 수집 (set 으로 중복 제거)
  counterpart_ids = {str(p["partner_user_id"]) for p in partners}
  in_clause = f"({','.join(counterpart_ids)})"  # UUID 는 안전 문자만 포함, 따옴표 불필요

  # 2) 단일 양방향 쿼리 — me ↔ counterparts (created_at DESC)
  result = await asyncio.to_thread(lambda: client.table("orders")
      .select("id, buyer_id, seller_id, total_amount, delivery_date, created_at, status")
      .is_("deleted_at", None)
      .neq("status", "CANCELLED")
      .or_(
          f"and(buyer_id.eq.{my_user_id},seller_id.in.{in_clause}),"
          f"and(seller_id.eq.{my_user_id},buyer_id.in.{in_clause})"
      )
      .order("created_at", desc=True)
      .execute()
  )

  # 3) 메모리에서 counterpart_id 별 첫 row 만 픽업 (이미 DESC 정렬됨)
  latest_by_counterpart: dict[str, dict] = {}
  for o in result.data or []:
      counterpart = o["seller_id"] if o["buyer_id"] == my_user_id else o["buyer_id"]
      if counterpart not in latest_by_counterpart:
          latest_by_counterpart[counterpart] = o
  ```
  - `get_stats` 의 단건 양방향 패턴 (단일 partner 대상) 을 다건으로 확장한 형태.
  - PostgREST `in.(...)` 문법 — UUID/숫자처럼 안전 문자만 들어가는 컬럼이면 따옴표 없이 OK. 문자열·검색어를 IN 으로 넣을 때는 PostgREST 의 `or_` PEG 파서가 깨질 수 있어 escape 필요.
  - partners 1페이지 (limit 20) × 평균 N 건 주문 = 단일 쿼리 1회로 끝. counterpart 가 비어있으면 쿼리 자체를 스킵.
  - `or_()` 안의 `and(buyer_id.eq.X,seller_id.in.(...))` — PostgREST 는 한 줄 안에 `and(...)` 와 `in.(...)` 를 함께 쓸 수 있지만 인용/공백에 민감. PEP 끊어쓰기 금지.

- **created_at (UTC TIMESTAMPTZ) → KST 날짜 변환 헬퍼 (검증됨, 2026-04-28)**: Supabase 에서 받은 `created_at` 은 보통 ISO 문자열 (`2026-04-28T05:30:00+00:00` 또는 `Z` suffix). KST 날짜 (YYYY-MM-DD) 가 필요할 때 단순 `[:10]` slice 는 자정 부근에서 하루 어긋난다. `Asia/Seoul = UTC+9` 고정 (DST 없음) 이라 `timezone(timedelta(hours=9))` 상수로 충분.
  ```python
  _KST = timezone(timedelta(hours=9))

  @staticmethod
  def _created_at_to_kst_date_str(created_at) -> Optional[str]:
      if not created_at:
          return None
      try:
          if isinstance(created_at, str):
              dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
          else:
              dt = created_at
          if dt.tzinfo is None:
              dt = dt.replace(tzinfo=timezone.utc)
          return dt.astimezone(_KST).date().isoformat()
      except Exception:
          return str(created_at)[:10] if created_at else None
  ```
  - `Z` suffix 처리 필수 — Python `datetime.fromisoformat` 은 3.11+ 부터만 `Z` 직접 파싱 지원. `replace("Z", "+00:00")` 가 안전하다.
  - `delivery_date` 같은 DATE 컬럼은 timezone 불필요 — 그대로 `[:10]` slice.

- **service-role-only INSERT 테이블 패턴 (notifications, 2026-04-29)**: 서버 내부에서만 emit 하고 클라이언트 직접 INSERT 를 차단하려면 RLS 에서 INSERT 정책 자체를 정의하지 않으면 된다 (SELECT/UPDATE 만 정의). PostgreSQL 의 RLS 는 화이트리스트 모델이라 정책이 없으면 anon/authenticated 는 INSERT 불가, service_role 은 RLS 우회로 INSERT 가능. notifications 테이블이 이 패턴의 첫 적용 사례 — 알림 INSERT 는 항상 백엔드 서비스(`notification_service.emit`)를 거치고 외부 노출 엔드포인트(`POST /notifications`) 를 두지 않는다. SELECT 는 본인만 (`user_id IN (SELECT id FROM users WHERE supabase_uid = auth.uid())`), UPDATE 도 동일.

- **soft delete 컬럼 보유 테이블 갱신 (2026-04-29)**: `deleted_at` 보유 = `users, products, partners, orders, calendar_events, messages, subscriptions` (7개). `deleted_at` 미보유 = `order_items, chat_rooms, ai_conversations, subscription_items, negotiation_history, delivery_date_change_history, notifications`. 알림은 일시성 데이터라 soft delete 미적용 — 향후 TTL/archive 정책 추가 시 재검토.

- **LLM 추론 category ↔ DB 저장 category 불일치 fallback 패턴 (2026-05-02, agent_tools.find_sellers_by_product 버그 수정)**: AI 도우미 도구가 `category` 인자를 받아 PostgREST 쿼리에 `eq("category", ...)` 로 박을 때, LLM 이 사용자 발화("옥수수 판매자 찾아줘")에서 추론한 카테고리(예: `GRAIN`)와 실제 DB 에 저장된 카테고리(예: `VEGETABLE`)가 어긋나면 결과가 0건이 되어 LLM 이 "판매자 없음"으로 잘못 응답한다. CHECK 제약이 13종으로 넓고(`fruit/vegetable/grain/...` 외 한국어 카테고리 포함), 동일 품목도 판매자별로 다른 카테고리로 등록될 수 있어 발생. 검증된 fallback 패턴 — 1차 조회 결과가 비어있고 category 가 `ALL` 이 아니면 category 필터만 제거하고 `product_name ilike` + `stock>0` + `deleted_at IS NULL` 로 2차 조회.
  ```python
  result = (query.gt("stock_quantity", 0).is_("deleted_at", None).execute())
  products = result.data or []

  # category 추론 실패 대비 fallback (product_name 은 유지하여 무관 품목 차단)
  if not products and category and category.upper() != "ALL":
      fallback_query = supabase.table("products").select("...")
      if product_name:
          fallback_query = fallback_query.ilike("name", f"%{product_name}%")
      result = fallback_query.gt("stock_quantity", 0).is_("deleted_at", None).execute()
      products = result.data or []
  ```
  - `category="ALL"` 호출은 1차에서 카테고리 필터를 안 걸므로 fallback 조건(`!= "ALL"`)에 막혀 중복 실행되지 않는다.
  - `product_name` 필터는 fallback 에서도 유지 → "옥수수" 키워드 매칭이 살아있어 무관 상품 혼입 없음.
  - 동일 함정이 잠재된 도구: `find_buyers_by_product`, `check_stock` 등 category 인자를 받는 모든 agent_tools 함수. 신규 도구 추가 시 동일 fallback 적용 권장.

- **supabase-py 2.x `update().execute()` representation 응답 비신뢰 패턴 (2026-04-29 notification 읽음 처리 버그 수정)**: supabase-py 2.11.0 의 `client.table(...).update(...).execute()` 는 UPDATE 가 실제로 성공해도 `result.data == []` 로 빈 배열을 반환하는 케이스가 있다 (representation 헤더 누락 / RLS 의 SELECT-after-UPDATE 단계 차단 / 일부 응답 경로). service_role 키 호출이라 RLS 자체는 우회되지만, 클라이언트 라이브러리 내부에서 representation 이 빠질 수 있어 `len(result.data)` 또는 `result.data[0]` 으로 성공 판단을 하면 안 된다. 검증된 회피 패턴:
  ```python
  # 단건 UPDATE — pre-select 로 존재/권한 확인 → UPDATE → 재조회 (3 step)
  pre = await asyncio.to_thread(
      lambda: self.table.select("id")
      .eq("id", nid_str).eq("user_id", user_id_str).limit(1).execute()
  )
  if not (pre.data or []):
      return {}                      # 라우터가 404 처리
  await asyncio.to_thread(
      lambda: self.table.update({...}).eq("id", nid_str).eq("user_id", user_id_str).execute()
  )
  after = await asyncio.to_thread(
      lambda: self.table.select("*")
      .eq("id", nid_str).eq("user_id", user_id_str).limit(1).execute()
  )
  return after.data[0] if after.data else {}

  # 다건 UPDATE — pre-count 로 affected row 수 측정 → UPDATE → count 반환
  pre = await asyncio.to_thread(
      lambda: self.table.select("id", count="exact")
      .eq("user_id", ...).eq("is_read", False).execute()
  )
  pending = pre.count or 0
  if pending == 0: return 0
  await asyncio.to_thread(
      lambda: self.table.update({...}).eq("user_id", ...).eq("is_read", False).execute()
  )
  return pending
  ```
  - 적용 위치: `notification_service.mark_read` / `mark_all_read`. 동일 함정이 있는 다른 서비스(예: 향후 partners/orders 의 단순 UPDATE 응답을 신뢰하는 코드)도 같은 패턴으로 보강 가능.
  - 비용: round-trip 1~2회 추가. 알림 읽음 같은 저빈도/단건 mutation 이라 무시 가능. 고빈도 경로(메시지 일괄 읽음 등)에서는 RPC SECURITY DEFINER 함수로 1 round-trip 처리 권장.
  - 증상 진단: 프론트에서 mutation 후 invalidate 해도 UI 가 갱신되지 않고, DB 직접 확인 시 데이터는 갱신되어 있으면 거의 이 함정이다.
