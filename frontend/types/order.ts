export type OrderStatus =
  | 'QUOTE_REQUESTED'
  | 'NEGOTIATING'
  | 'CONFIRMED'
  | 'PREPARING'
  | 'SHIPPING'
  | 'COMPLETED'
  | 'CANCELLED';

export interface OrderItem {
  id: string;
  order_id: string;
  product_id: string;
  quantity: number;
  unit_price: number;
  subtotal: number;
  notes: string | null;
  created_at: string;
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
  items: OrderItem[];
  created_at: string;
  updated_at: string;
}

export interface OrderItemCreate {
  product_id: string;
  quantity: number;
  unit_price: number;
  notes?: string;
}

export interface OrderCreate {
  seller_id: string;
  delivery_date?: string;
  delivery_address?: string;
  notes?: string;
  items: OrderItemCreate[];
}
