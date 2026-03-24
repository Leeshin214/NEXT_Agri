export type ProductCategory = 'FRUIT' | 'VEGETABLE' | 'GRAIN' | 'OTHER';
export type ProductStatus = 'NORMAL' | 'LOW_STOCK' | 'OUT_OF_STOCK' | 'SCHEDULED';
export type ProductUnit = 'kg' | 'box' | 'piece' | 'bag';

export interface Product {
  id: string;
  seller_id: string;
  name: string;
  category: ProductCategory;
  origin: string | null;
  spec: string | null;
  unit: ProductUnit;
  price_per_unit: number;
  stock_quantity: number;
  min_order_qty: number;
  status: ProductStatus;
  description: string | null;
  image_url: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProductCreate {
  name: string;
  category: ProductCategory;
  origin?: string;
  spec?: string;
  unit: ProductUnit;
  price_per_unit: number;
  stock_quantity?: number;
  min_order_qty?: number;
  description?: string;
}

export interface ProductUpdate {
  name?: string;
  category?: ProductCategory;
  origin?: string;
  spec?: string;
  unit?: ProductUnit;
  price_per_unit?: number;
  stock_quantity?: number;
  min_order_qty?: number;
  status?: ProductStatus;
  description?: string;
  image_url?: string;
}
