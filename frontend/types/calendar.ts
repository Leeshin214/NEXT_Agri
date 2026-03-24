export type EventType =
  | 'SHIPMENT'
  | 'DELIVERY'
  | 'MEETING'
  | 'QUOTE_DEADLINE'
  | 'ORDER'
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
