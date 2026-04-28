import type {
  CalendarEvent,
  EventType,
  OrderStatus,
  PartnerStatus,
  ProductStatus,
  SubscriptionStatus,
} from '@/types';

interface StatusConfig {
  label: string;
  className: string;
}

interface OrderStatusConfig extends StatusConfig {
  solidClassName: string;
}

interface SubscriptionStatusConfig extends StatusConfig {
  solidClassName: string;
}

export const PRODUCT_STATUS_CONFIG = {
  NORMAL: { label: '정상', className: 'bg-green-100 text-green-800' },
  LOW_STOCK: { label: '재고부족', className: 'bg-yellow-100 text-yellow-800' },
  OUT_OF_STOCK: { label: '품절', className: 'bg-red-100 text-red-800' },
  SCHEDULED: { label: '출하예정', className: 'bg-blue-100 text-blue-800' },
} as const satisfies Record<ProductStatus, StatusConfig>;

export const ORDER_STATUS_CONFIG = {
  QUOTE_REQUESTED: {
    label: '견적대기',
    className: 'bg-gray-100 text-gray-700',
    solidClassName: 'bg-gray-500',
  },
  NEGOTIATING: {
    label: '협상중',
    className: 'bg-orange-100 text-orange-800',
    solidClassName: 'bg-orange-500',
  },
  CONFIRMED: {
    label: '주문확정',
    className: 'bg-blue-100 text-blue-800',
    solidClassName: 'bg-blue-500',
  },
  PREPARING: {
    label: '출하준비',
    className: 'bg-purple-100 text-purple-800',
    solidClassName: 'bg-purple-500',
  },
  SHIPPING: {
    label: '배송중',
    className: 'bg-indigo-100 text-indigo-800',
    solidClassName: 'bg-indigo-500',
  },
  COMPLETED: {
    label: '완료',
    className: 'bg-green-100 text-green-800',
    solidClassName: 'bg-green-500',
  },
  CANCELLED: {
    label: '취소',
    className: 'bg-red-100 text-red-800',
    solidClassName: 'bg-red-500',
  },
} as const satisfies Record<OrderStatus, OrderStatusConfig>;

/**
 * V1.6 — 양방향 승인 모델.
 *
 * - PENDING: deprecated. V1.5 이전 데이터 호환을 위해 유지.
 *            (양쪽 row 가 동일 PENDING 으로 같이 보일 수 있음)
 * - PENDING_OUTGOING: 본인이 보낸 요청 (수락 대기) — 노란색
 * - PENDING_INCOMING: 받은 요청 (수락/거절 가능) — 파란색
 */
export const PARTNER_STATUS_CONFIG = {
  ACTIVE: { label: '활성', className: 'bg-green-100 text-green-800' },
  INACTIVE: { label: '비활성', className: 'bg-gray-100 text-gray-600' },
  PENDING: { label: '대기', className: 'bg-yellow-100 text-yellow-800' },
  PENDING_OUTGOING: {
    label: '보낸 요청',
    className: 'bg-yellow-100 text-yellow-800',
  },
  PENDING_INCOMING: {
    label: '받은 요청',
    className: 'bg-blue-100 text-blue-800',
  },
} as const satisfies Record<PartnerStatus, StatusConfig>;

/**
 * V1.6 — 정기배송 양방향 승인 모델.
 *
 * 캘린더 가상 이벤트 색은 EVENT_TYPE_COLOR_CLASS.SUBSCRIPTION 와 일관성 있게
 * ACTIVE = bg-purple-500 (진한 보라). 상태 뱃지(className)는 옅은 보라 톤.
 */
export const SUBSCRIPTION_STATUS_CONFIG = {
  PENDING: {
    label: '승인 대기',
    className: 'bg-amber-100 text-amber-800',
    solidClassName: 'bg-amber-500',
  },
  ACTIVE: {
    label: '진행중',
    className: 'bg-purple-100 text-purple-800',
    solidClassName: 'bg-purple-500',
  },
  PAUSED: {
    label: '일시정지',
    className: 'bg-gray-100 text-gray-700',
    solidClassName: 'bg-gray-500',
  },
  ENDED: {
    label: '종료',
    className: 'bg-slate-100 text-slate-700',
    solidClassName: 'bg-slate-500',
  },
  CANCELLED: {
    label: '취소',
    className: 'bg-red-100 text-red-700',
    solidClassName: 'bg-red-500',
  },
  REJECTED: {
    label: '거절',
    className: 'bg-rose-100 text-rose-700',
    solidClassName: 'bg-rose-500',
  },
} as const satisfies Record<SubscriptionStatus, SubscriptionStatusConfig>;

export const STATUS_CONFIG: Record<string, StatusConfig> = {
  ...PRODUCT_STATUS_CONFIG,
  ...ORDER_STATUS_CONFIG,
  ...PARTNER_STATUS_CONFIG,
};

/**
 * V1.6 — 정기배송 색을 진한 보라로 통일.
 * SUBSCRIPTION 가상 이벤트는 SUBSCRIPTION_STATUS_CONFIG.ACTIVE.solidClassName 과 동일.
 */
export const EVENT_TYPE_COLOR_CLASS: Record<EventType, string> = {
  SHIPMENT: 'bg-blue-500',
  DELIVERY: 'bg-green-500',
  MEETING: 'bg-purple-500',
  QUOTE_DEADLINE: 'bg-red-500',
  ORDER: 'bg-orange-500',
  SUBSCRIPTION: 'bg-purple-500',
  OTHER: 'bg-gray-500',
};

export const EVENT_TYPE_LABEL: Record<EventType, string> = {
  SHIPMENT: '출하',
  DELIVERY: '입고',
  MEETING: '미팅',
  QUOTE_DEADLINE: '견적마감',
  ORDER: '주문',
  SUBSCRIPTION: '정기배송',
  OTHER: '기타',
};

export function getStatusConfig(status: string): StatusConfig {
  return (
    STATUS_CONFIG[status] ?? {
      label: status,
      className: 'bg-gray-100 text-gray-700',
    }
  );
}

/**
 * 캘린더 일정 색상 클래스
 * - 주문 일정(order_status 있음)이면 ORDER_STATUS_CONFIG.solidClassName 사용 (주문/견적 페이지와 색 일치)
 * - 그 외(MEETING 등)는 EVENT_TYPE_COLOR_CLASS fallback
 */
export function getCalendarEventColorClass(
  event: Pick<CalendarEvent, 'event_type' | 'order_status'>
): string {
  if (event.order_status && event.order_status in ORDER_STATUS_CONFIG) {
    return ORDER_STATUS_CONFIG[event.order_status].solidClassName;
  }
  return EVENT_TYPE_COLOR_CLASS[event.event_type] ?? EVENT_TYPE_COLOR_CLASS.OTHER;
}

/**
 * 캘린더 일정 한글 라벨
 * - 주문 일정이면 ORDER_STATUS_CONFIG.label (견적대기, 협상중, 주문확정 등)
 * - 그 외는 EVENT_TYPE_LABEL (출하, 입고, 미팅 등)
 *
 * 백엔드는 주문 관련 일정의 event_type을 항상 'ORDER'로 송출하므로
 * order_status 우선 매핑이 필수 (없으면 모든 주문 일정이 '주문'으로 표시됨).
 */
export function getCalendarEventLabel(
  event: Pick<CalendarEvent, 'event_type' | 'order_status'>
): string {
  if (event.order_status && event.order_status in ORDER_STATUS_CONFIG) {
    return ORDER_STATUS_CONFIG[event.order_status].label;
  }
  return EVENT_TYPE_LABEL[event.event_type] ?? '기타';
}
