export type OrderStatus =
  | 'QUOTE_REQUESTED'
  | 'NEGOTIATING'
  | 'CONFIRMED'
  | 'PREPARING'
  | 'SHIPPING'
  | 'COMPLETED'
  | 'CANCELLED';

export type CounterOfferStatus =
  | 'PENDING'
  | 'ACCEPTED'
  | 'REJECTED'
  | 'SUPERSEDED';

export type FromRole = 'SELLER' | 'BUYER';

/**
 * 견적/주문 항목 입력 (생성·수정·협상가 공용)
 * 백엔드 Pydantic의 OrderItemCreate / OrderItemUpdate 양쪽에 그대로 매핑된다.
 */
export interface OrderItemInput {
  product_id: string;
  quantity: number;
  unit_price: number;
  notes?: string;
}

/**
 * 기존 코드와의 호환을 위한 별칭. (예전: OrderItemCreate)
 * 새 코드는 OrderItemInput을 사용한다.
 */
export type OrderItemCreate = OrderItemInput;

export interface OrderItem {
  id: string;
  order_id: string;
  product_id: string;
  quantity: number;
  unit_price: number;
  subtotal: number;
  notes: string | null;
  created_at: string;
  // 백엔드 join 필드 — products 임베딩에서 평탄화. 상품 soft-delete 시 null.
  product_name?: string | null;
  product_unit?: string | null;
  product_category?: string | null;
}

export interface Order {
  id: string;
  order_number: string;
  buyer_id: string;
  seller_id: string;
  status: OrderStatus;
  total_amount: number | null;
  delivery_date: string | null;
  delivery_address: string | null;
  notes: string | null;
  cancellation_reason: string | null;
  cancelled_at: string | null;
  cancelled_by: string | null;
  items: OrderItem[];
  // 백엔드 join 필드 — users!buyer_id / users!seller_id 임베딩에서 평탄화. 사용자 soft-delete 시 null.
  buyer_name?: string | null;
  buyer_company?: string | null;
  seller_name?: string | null;
  seller_company?: string | null;
  // V1.5 Phase 2 — 정기배송 자동 생성 주문 추적용. 일반 주문은 null.
  subscription_id?: string | null;
  subscription_round?: number | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  /** 백엔드가 제공하는 상품 요약 (예: "사과 외 2건"). 미제공 시 items[0].product_name 으로 폴백. */
  product_summary?: string | null;
}

export interface OrderCreate {
  seller_id: string;
  delivery_date?: string;
  delivery_address?: string;
  notes?: string;
  items: OrderItemInput[];
}

export interface OrderUpdate {
  delivery_date?: string;
  delivery_address?: string;
  notes?: string;
  items?: OrderItemInput[];
}

export interface CounterOfferCreate {
  proposed_total_amount: number;
  proposed_items?: OrderItemInput[];
  notes?: string;
}

export interface CounterOffer {
  id: string;
  order_id: string;
  from_user_id: string;
  from_role: FromRole;
  proposed_total_amount: number;
  proposed_items: OrderItemInput[] | null;
  notes: string | null;
  status: CounterOfferStatus;
  responded_at: string | null;
  responded_by: string | null;
  created_at: string;
}

// 납품일 변경 요청 (delivery_date_change_history)
// 백엔드 DeliveryDateChangeResponse Pydantic 스키마와 동기화.
export type DeliveryDateChangeStatus =
  | 'PENDING'
  | 'ACCEPTED'
  | 'REJECTED'
  | 'SUPERSEDED';

export interface DeliveryDateChange {
  id: string;
  order_id: string;
  from_user_id: string;
  from_role: FromRole;
  /** YYYY-MM-DD */
  proposed_delivery_date: string;
  notes: string | null;
  status: DeliveryDateChangeStatus;
  responded_at: string | null;
  responded_by: string | null;
  created_at: string;
  updated_at: string;
  // 백엔드 join 필드 — users 임베딩에서 평탄화
  from_user_name: string | null;
  from_user_company: string | null;
}

export interface DeliveryDateChangeCreate {
  /** YYYY-MM-DD */
  proposed_delivery_date: string;
  notes?: string;
}
