/**
 * 구매자(BUYER) 재고 타입.
 *
 * 백엔드 BuyerInventoryResponse Pydantic 스키마와 동기화.
 * - 자동 누적: 주문 상태가 COMPLETED 로 전환될 때 백엔드 order_service 가 자동 추가/누적.
 * - PostgREST embed 파생 필드(product_*, seller_*) 는 상품/판매자 soft-delete 시 null.
 */

import type { ProductCategory } from './product';

/**
 * 정렬 옵션 — 백엔드 list_buyer_inventory 의 sort_by 와 동기화.
 * - "recent"   : last_added_at DESC (NULLS LAST) — 기본
 * - "quantity" : quantity DESC
 * - "name"     : products.name ASC
 */
export type BuyerInventorySortBy = 'recent' | 'quantity' | 'name';

export interface BuyerInventory {
  id: string;
  buyer_id: string;
  product_id: string;
  quantity: number;
  unit: string | null;
  /** 마지막 입고(최근 COMPLETED) 시각. ISO8601. */
  last_added_at: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  // PostgREST embed 파생 필드 — 상품/판매자 soft-delete 시 null.
  product_name: string | null;
  product_category: ProductCategory | null;
  product_image_url: string | null;
  seller_name: string | null;
  seller_company: string | null;
}

/** PATCH /buyer/inventory/{id} 요청 바디. quantity 는 0 이상. */
export interface BuyerInventoryUpdatePayload {
  quantity?: number;
  notes?: string;
}

/** GET /buyer/inventory 쿼리 파라미터. */
export interface BuyerInventoryListParams {
  search?: string;
  product_id?: string;
  page?: number;
  limit?: number;
  sort_by?: BuyerInventorySortBy;
}
