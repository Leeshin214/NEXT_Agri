/**
 * 대체 거래처 자동 추천 (alternative_partner_recommendations) 응답 타입.
 * 백엔드 `app/schemas/alternative.py` 와 1:1 동기화.
 *
 * 판매자가 활성 주문을 취소하면 백엔드가 자동으로:
 *   1) 같은 카테고리·LLM 본질 동일성 통과 후보 상위 3건 선정
 *   2) 각 후보에 자동 QUOTE_REQUESTED 견적 주문 생성 (auto_order_id 채워짐)
 *   3) 이 응답으로 저장 → 구매자가 주문 상세 패널 / 알림으로 확인.
 */

/**
 * 가격 결정 전략 (2026-05-07).
 * - ORIGINAL_LOWER: 기존 주문가가 더 저렴 → 그 단가로 협상가 제시 (NEGOTIATING)
 * - CANDIDATE_LOWER: 새 셀러 표시가가 더 저렴 → 그 단가로 주문 (QUOTE_REQUESTED)
 * - EQUAL: 동일 단가
 * - FALLBACK_ORIGINAL: 새 셀러 표시가 누락 → 원래 단가 사용
 * - FALLBACK_CANDIDATE: 원래 단가 누락 → 새 셀러 표시가 사용
 */
export type AlternativePriceStrategy =
  | 'ORIGINAL_LOWER'
  | 'CANDIDATE_LOWER'
  | 'EQUAL'
  | 'FALLBACK_ORIGINAL'
  | 'FALLBACK_CANDIDATE';

export interface AlternativeCandidate {
  seller_id: string;
  seller_name: string;
  seller_company: string;
  product_id: string;
  product_name: string;
  stock_quantity: number;
  price_per_unit: number;
  unit: string;
  trade_count: number;
  last_trade_date: string | null;
  /** 자동 견적 성공 시 채워짐 — 클릭하면 새 주문 상세로 점프 가능. 실패 시 null + auto_order_error. */
  auto_order_id: string | null;
  auto_order_number: string | null;
  auto_order_error: string | null;
  /** 가격 결정 메타 (2026-05-07). 옛 row 는 null/누락 — UI 가드 필요. */
  original_unit_price?: number | null;
  effective_unit_price?: number | null;
  price_strategy?: AlternativePriceStrategy | null;
}

export interface AlternativeRecommendation {
  id: string;
  cancelled_order_id: string;
  buyer_id: string;
  candidates: AlternativeCandidate[];
  reason: string;
  found_count: number;
  created_at: string;
}
