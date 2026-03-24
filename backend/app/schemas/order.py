from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class OrderItemCreate(BaseModel):
    product_id: UUID
    quantity: int
    unit_price: int
    notes: Optional[str] = None


class OrderItemResponse(BaseModel):
    id: UUID
    order_id: UUID
    product_id: UUID
    quantity: int
    unit_price: int
    subtotal: int
    notes: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class OrderCreate(BaseModel):
    seller_id: UUID
    delivery_date: Optional[date] = None
    delivery_address: Optional[str] = None
    notes: Optional[str] = None
    items: list[OrderItemCreate]


class OrderStatusUpdate(BaseModel):
    status: str


class OrderResponse(BaseModel):
    id: UUID
    order_number: str
    buyer_id: UUID
    seller_id: UUID
    status: str
    total_amount: Optional[int] = None
    delivery_date: Optional[date] = None
    delivery_address: Optional[str] = None
    notes: Optional[str] = None
    items: list[OrderItemResponse] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
