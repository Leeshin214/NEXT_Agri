/**
 * 정기배송 (Subscription) 타입 정의
 *
 * V1.5 Phase 2 — backend schemas/subscription.py 와 일대일 매핑.
 * V1.6        — PENDING / REJECTED 상태 + created_by 필드 추가 (양방향 승인 모델).
 */

export type SubscriptionFrequency = 'WEEKLY' | 'BIWEEKLY' | 'MONTHLY';

/**
 * V1.6 양방향 승인:
 *   PENDING   — 생성 직후 상대 수락 대기
 *   ACTIVE    — 수락되어 운영중
 *   PAUSED    — 일시정지
 *   ENDED     — 종료
 *   CANCELLED — 취소
 *   REJECTED  — 상대가 거절
 */
export type SubscriptionStatus =
  | 'PENDING'
  | 'ACTIVE'
  | 'PAUSED'
  | 'ENDED'
  | 'CANCELLED'
  | 'REJECTED';

export interface SubscriptionItem {
  id: string;
  subscription_id: string;
  product_id: string;
  product_name: string | null;
  quantity: number;
  unit_price: number;
  unit: string;
  created_at: string;
}

export interface SubscriptionItemCreate {
  product_id: string;
  quantity: number;
  unit_price: number;
  unit: string;
}

export interface Subscription {
  id: string;
  seller_id: string;
  buyer_id: string;
  partner_id: string | null;
  frequency: SubscriptionFrequency;
  day_of_week: number | null;
  day_of_month: number | null;
  start_date: string;
  end_date: string | null;
  next_delivery_date: string;
  status: SubscriptionStatus;
  delivery_address: string | null;
  notes: string | null;
  total_amount: number;
  /**
   * V1.6 — 정기배송을 만든 사용자 (수락 권한 판단용).
   * V1.5 이전 데이터(NULL)는 누구나 수락 가능.
   */
  created_by: string | null;
  created_at: string;
  updated_at: string;
  items: SubscriptionItem[];
  // 거래처 상대방 정보
  seller_name: string | null;
  seller_company: string | null;
  buyer_name: string | null;
  buyer_company: string | null;
}

export interface SubscriptionCreate {
  seller_id: string;
  buyer_id: string;
  partner_id?: string | null;
  frequency: SubscriptionFrequency;
  day_of_week?: number | null;
  day_of_month?: number | null;
  start_date: string;
  end_date?: string | null;
  delivery_address?: string | null;
  notes?: string | null;
  items: SubscriptionItemCreate[];
}

export interface SubscriptionUpdate {
  frequency?: SubscriptionFrequency;
  day_of_week?: number | null;
  day_of_month?: number | null;
  start_date?: string;
  end_date?: string | null;
  status?: SubscriptionStatus;
  delivery_address?: string | null;
  notes?: string | null;
}

/**
 * 거래처 거래 통계 (GET /partners/{id}/stats)
 *
 * Phase 2 에서 신규로 사용. 다른 도메인에서도 import 일관성 유지를 위해
 * subscription.ts 가 아닌 partner.ts 에 함께 두는 것도 고려했으나
 * Subscription 도메인과 함께 노출되는 점이 강해 여기에 둔다.
 * `types/index.ts` 에서 모두 re-export.
 */
export interface PartnerStats {
  total_orders: number;
  total_amount: number;
  last_order_date: string | null;
  active_subscriptions: number;
}
