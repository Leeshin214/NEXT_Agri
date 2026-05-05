export interface ChatRoom {
  id: string;
  order_id: string | null;
  seller_id: string;
  buyer_id: string;
  last_message: string | null;
  last_message_at: string | null;
  created_at: string;
  updated_at: string;
  partner_name: string | null;
  partner_company: string | null;
  unread_count: number;
  order_number?: string | null;
  first_product_name?: string | null;
}

/**
 * 주문 협상 ↔ 채팅 양방향 연결을 위한 메시지 타입.
 * 백엔드 chat_service.ALLOWED_MESSAGE_TYPES 와 동기화된다.
 *
 * - TEXT             : 일반 사용자 메시지 (기본)
 * - SYSTEM           : 시스템 안내 (견적 요청 자동 알림 등). 가운데 회색 안내 박스로 렌더
 * - COUNTER_OFFER    : 협상가 제시 — 카드형 강조 박스 + 수락/거절 버튼
 * - OFFER_ACCEPTED   : 협상가 수락 — 초록 카드
 * - OFFER_REJECTED   : 협상가 거절 — 회색 카드
 * - ORDER_STATUS     : 주문 상태 변경 — 가운데 박스 (StatusBadge 활용)
 * - ORDER_CANCELLED  : 주문 취소 — 빨간 카드
 */
export type MessageType =
  | 'TEXT'
  | 'SYSTEM'
  | 'COUNTER_OFFER'
  | 'OFFER_ACCEPTED'
  | 'OFFER_REJECTED'
  | 'ORDER_STATUS'
  | 'ORDER_CANCELLED'
  // 납품일 변경 요청·승인 (2026-04-29 추가)
  | 'DELIVERY_DATE_CHANGE'
  | 'DELIVERY_DATE_ACCEPTED'
  | 'DELIVERY_DATE_REJECTED'
  // 취소 요청 워크플로우 (2026-05-05 추가)
  | 'CANCEL_REQUESTED'
  | 'CANCEL_REQUEST_REJECTED';

/**
 * 협상 의도 감지 결과 (US-2 — 2026-05-04 추가).
 * 평문 메시지에서 백엔드가 추출한 가격/수량/품목 후보. 자동 등록 X — 발신자 본인이
 * [등록] 클릭 시 기존 PriceOfferPopover 흐름으로 prefill.
 *
 * 백엔드 schemas/chat.py NegotiationDraft 와 1:1 매칭. messages.metadata.draft_negotiation
 * JSONB 에 저장되어 새로고침 후에도 복원 가능. dismissed_at 채워지면 카드 숨김.
 */
export interface NegotiationDraft {
  product_name: string | null;
  quantity: number | null;
  unit: string | null;
  unit_price: number | null;
  confidence: number;
  detected_at: string;
  dismissed_at: string | null;
}

/**
 * 메시지의 metadata 필드는 message_type 별로 형태가 다르다.
 * 모든 키는 optional 로 선언해 서버 응답을 그대로 받을 수 있게 한다.
 * 페이지/컴포넌트 단계에서 message_type 으로 좁힌 뒤 사용한다.
 */
export interface MessageMetadata {
  // US-2 — 평문 메시지에서 감지된 협상 후보 (TEXT 타입에만 채워짐)
  draft_negotiation?: NegotiationDraft;
  // SYSTEM (견적 요청 알림)
  order_id?: string;
  order_number?: string;
  total_amount?: number;
  // COUNTER_OFFER
  offer_id?: string;
  proposed_total_amount?: number;
  from_role?: 'SELLER' | 'BUYER';
  notes?: string;
  status?: 'PENDING' | 'ACCEPTED' | 'REJECTED' | 'SUPERSEDED';
  // OFFER_ACCEPTED
  accepted_amount?: number;
  // ORDER_STATUS
  from_status?: string;
  to_status?: string;
  // ORDER_CANCELLED
  reason?: string;
  cancelled_by?: string;
  // DELIVERY_DATE_CHANGE / DELIVERY_DATE_ACCEPTED / DELIVERY_DATE_REJECTED (2026-04-29)
  // 백엔드 _emit_chat_event broadcast 와 동기화.
  change_id?: string;
  /** YYYY-MM-DD — DELIVERY_DATE_CHANGE / DELIVERY_DATE_REJECTED */
  proposed_delivery_date?: string;
  /** YYYY-MM-DD — DELIVERY_DATE_ACCEPTED 시 확정된 날짜 */
  accepted_delivery_date?: string;
  /** YYYY-MM-DD — DELIVERY_DATE_CHANGE 직전 orders.delivery_date (참고용) */
  previous_delivery_date?: string;
  // 향후 확장 필드
  [key: string]: unknown;
}

export interface Message {
  id: string;
  room_id: string;
  sender_id: string;
  content: string;
  is_read: boolean;
  created_at: string;
  deleted_at?: string | null;
  // 주문 협상 ↔ 채팅 양방향 연결 (2026-04-27 추가)
  message_type?: MessageType;
  metadata?: MessageMetadata | null;
}

// 백엔드 services/agent_tools.py find_alternative_partners 의 alternatives 항목과 매칭
// 필드 이름은 백엔드 dict 그대로 유지 — name/company_name/trade_count 등
export interface AlternativePartner {
  user_id: string;
  name: string;
  company_name?: string;
  // 거래 이력 관련
  trade_count?: number;
  last_trade_date?: string | null;
  // 대표 상품 정보 (BUYER 호출 시 채워짐)
  stock_quantity?: number | null;
  price_per_unit?: number | null;
  unit?: string;
  product_name?: string;
  category?: string;
  // 연락처 (있을 때만)
  phone?: string;
  email?: string;
}
