/**
 * 알림(Notification) 타입.
 *
 * 백엔드 `app/schemas/notification.py` 와 1:1 동기화.
 * INSERT 는 서버 내부 emit 으로만 발생하므로 클라이언트에서 만드는 타입(Create) 은 없다.
 */

export type NotificationType =
  | 'NEW_MESSAGE'
  | 'COUNTER_OFFER'
  | 'OFFER_ACCEPTED'
  | 'OFFER_REJECTED'
  | 'DELIVERY_DATE_CHANGE'
  | 'DELIVERY_DATE_ACCEPTED'
  | 'DELIVERY_DATE_REJECTED'
  | 'ORDER_STATUS';

export interface Notification {
  id: string;
  user_id: string;
  type: NotificationType;
  title: string;
  body: string;
  link_url: string | null;
  order_id: string | null;
  room_id: string | null;
  is_read: boolean;
  created_at: string;
  read_at: string | null;
}

/**
 * GET /notifications 응답의 meta.
 * SuccessResponse<Notification[]>.meta 자리에 들어온다.
 */
export interface NotificationListMeta {
  unread_count: number;
  total: number;
}

/**
 * GET /notifications/unread-count 응답 data.
 * 백엔드는 SuccessResponse<UnreadCountResponse> 로 감싸 반환한다.
 */
export interface UnreadCountData {
  unread_count: number;
}

/**
 * POST /notifications/read-all 응답 data.
 */
export interface MarkAllReadData {
  updated: number;
}
