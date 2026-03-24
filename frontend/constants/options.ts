// 상품 카테고리
export const CATEGORY_OPTIONS = [
  { value: 'FRUIT', label: '과일' },
  { value: 'VEGETABLE', label: '채소' },
  { value: 'GRAIN', label: '곡물' },
  { value: 'OTHER', label: '기타' },
] as const;

// 상품 상태
export const PRODUCT_STATUS_OPTIONS = [
  { value: 'NORMAL', label: '정상' },
  { value: 'LOW_STOCK', label: '재고부족' },
  { value: 'OUT_OF_STOCK', label: '품절' },
  { value: 'SCHEDULED', label: '출하예정' },
] as const;

// 상품 단위
export const UNIT_OPTIONS = [
  { value: 'kg', label: 'kg' },
  { value: 'box', label: '박스' },
  { value: 'piece', label: '개' },
  { value: 'bag', label: '포대' },
] as const;

// 주문 상태
export const ORDER_STATUS_OPTIONS = [
  { value: 'QUOTE_REQUESTED', label: '견적대기' },
  { value: 'NEGOTIATING', label: '협상중' },
  { value: 'CONFIRMED', label: '주문확정' },
  { value: 'PREPARING', label: '출하준비' },
  { value: 'SHIPPING', label: '배송중' },
  { value: 'COMPLETED', label: '완료' },
  { value: 'CANCELLED', label: '취소' },
] as const;

// 일정 유형
export const EVENT_TYPE_OPTIONS = [
  { value: 'SHIPMENT', label: '출하' },
  { value: 'DELIVERY', label: '입고' },
  { value: 'MEETING', label: '미팅' },
  { value: 'QUOTE_DEADLINE', label: '견적마감' },
  { value: 'ORDER', label: '주문' },
  { value: 'OTHER', label: '기타' },
] as const;

// 거래처 상태
export const PARTNER_STATUS_OPTIONS = [
  { value: 'ACTIVE', label: '활성' },
  { value: 'INACTIVE', label: '비활성' },
  { value: 'PENDING', label: '대기' },
] as const;
