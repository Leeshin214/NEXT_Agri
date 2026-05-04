export type ProductCategory = 'FRUIT' | 'VEGETABLE' | 'GRAIN' | 'OTHER';
export type ProductStatus = 'NORMAL' | 'LOW_STOCK' | 'OUT_OF_STOCK' | 'SCHEDULED';
export type ProductUnit = 'kg' | 'box' | 'piece' | 'bag';

export interface Product {
  id: string;
  seller_id: string;
  name: string;
  category: ProductCategory;
  origin: string | null;
  spec: string | null;
  unit: ProductUnit;
  price_per_unit: number;
  stock_quantity: number;
  min_order_qty: number;
  status: ProductStatus;
  description: string | null;
  image_url: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProductCreate {
  name: string;
  category: ProductCategory;
  origin?: string;
  spec?: string;
  unit: ProductUnit;
  price_per_unit: number;
  stock_quantity?: number;
  min_order_qty?: number;
  description?: string;
}

export interface ProductUpdate {
  name?: string;
  category?: ProductCategory;
  origin?: string;
  spec?: string;
  unit?: ProductUnit;
  price_per_unit?: number;
  stock_quantity?: number;
  min_order_qty?: number;
  status?: ProductStatus;
  description?: string;
  image_url?: string;
}

// ===========================================
// 상품 상세 페이지 보강 응답 (B.1, 2026-05-04)
// 백엔드 schemas/product.py 의 ProductDetailResponse / ProductMinimal 와 동기화.
// ===========================================
/**
 * 같은 판매자의 다른 상품 — 상세 페이지 측면 노출용 미니 카드.
 * Product 의 일부 필드만 사용 (description / origin / spec 제외).
 */
export interface ProductMinimal {
  id: string;
  name: string;
  category: ProductCategory;
  unit: ProductUnit;
  price_per_unit: number;
  stock_quantity: number;
  status: ProductStatus;
  image_url: string | null;
}

/**
 * 거래처 관계 상태 (BUYER 가 본인 ↔ 판매자 partners.status 를 본 값).
 * - 'ACTIVE'           : 거래 중
 * - 'PENDING_OUTGOING' : 본인이 신청 후 대기
 * - 'PENDING_INCOMING' : 상대가 신청 → 본인 응답 대기
 * - 'INACTIVE'         : 비활성/거절 이력
 * - null               : 거래처 등록 이력 없음 (신규)
 */
export type PartnerRelationshipStatus =
  | 'ACTIVE'
  | 'PENDING_OUTGOING'
  | 'PENDING_INCOMING'
  | 'INACTIVE';

/**
 * GET /products/{id}/detail 응답.
 * 기존 Product 필드 + 판매자 join + (BUYER 한정) 거래 통계 + 같은 판매자 다른 상품.
 */
export interface ProductDetailResponse extends Product {
  seller_name: string | null;
  seller_company: string | null;
  partner_relationship_status: PartnerRelationshipStatus | null;
  previous_order_count: number;
  completed_order_count: number;
  other_seller_products: ProductMinimal[];
}
