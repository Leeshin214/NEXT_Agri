import type { OrderStatus } from './order';

export type EventType =
  | 'SHIPMENT'
  | 'DELIVERY'
  | 'MEETING'
  | 'QUOTE_DEADLINE'
  | 'ORDER'
  | 'SUBSCRIPTION'  // V1.5 Phase 2 — 정기배송 가상 이벤트 (프론트에서만 합성)
  | 'OTHER';

export interface CalendarEvent {
  id: string;
  user_id: string;
  order_id: string | null;
  title: string;
  event_type: EventType;
  event_date: string;
  start_time: string | null;
  end_time: string | null;
  description: string | null;
  is_allday: boolean;
  created_at: string;
  order_number: string | null;
  product_name: string | null;
  order_status: OrderStatus | null;
}

export interface CalendarEventCreate {
  order_id?: string;
  title: string;
  event_type: EventType;
  event_date: string;
  start_time?: string;
  end_time?: string;
  description?: string;
  is_allday?: boolean;
}
