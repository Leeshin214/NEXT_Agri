export interface ChatRoom {
  id: string;
  order_id: string | null;
  seller_id: string;
  buyer_id: string;
  last_message: string | null;
  last_message_at: string | null;
  created_at: string;
  partner_name: string | null;
  partner_company: string | null;
  unread_count: number;
}

export interface Message {
  id: string;
  room_id: string;
  sender_id: string;
  content: string;
  is_read: boolean;
  created_at: string;
}
