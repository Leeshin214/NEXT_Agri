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
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  order_number    TEXT UNIQUE NOT NULL,   -- ORD-20240315-001
  buyer_id        UUID NOT NULL REFERENCES users(id),
  seller_id       UUID NOT NULL REFERENCES users(id),
  status          TEXT NOT NULL DEFAULT 'QUOTE_REQUESTED'
                    CHECK (status IN (
                      'QUOTE_REQUESTED', 'NEGOTIATING', 'CONFIRMED',
                      'PREPARING', 'SHIPPING', 'COMPLETED', 'CANCELLED'
                    )),
  total_amount    INTEGER,                -- 총 금액 (원)
  delivery_date   DATE,                   -- 납품 희망일
  delivery_address TEXT,
  notes           TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at      TIMESTAMPTZ
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
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
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

- **calendar_events에는 deleted_at 없음**: `calendar_events` 테이블 스키마에는 `deleted_at` 컬럼이 정의되어 있지 않다. `.is_("deleted_at", "null")` 필터를 적용하면 쿼리 오류가 발생한다. 이 테이블은 soft delete를 지원하지 않으므로 해당 필터를 생략한다.

- **BUYER의 주문 상품 조회 패턴**: 구매자가 최근 주문한 상품 목록을 가져올 때 직접 JOIN이 없으므로 3단계로 나눠 조회한다. orders(buyer_id) → order_items(order_id) → products(id). 각 단계를 별도 `asyncio.to_thread` 호출로 처리하고 product_ids는 set으로 중복 제거 후 `.in_()` 필터를 사용한다.

### 주의사항 & 함정

- **calendar_events soft delete 없음**: 다른 테이블과 달리 `calendar_events`는 `deleted_at` 컬럼이 없다. 일관성을 위해 추가하려면 마이그레이션이 필요하다. 현재는 해당 필터 없이 조회한다.
