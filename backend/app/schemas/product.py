from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class ProductCreate(BaseModel):
    name: str
    category: str
    origin: Optional[str] = None
    spec: Optional[str] = None
    unit: str
    price_per_unit: int
    stock_quantity: int = 0
    min_order_qty: int = 1
    description: Optional[str] = None


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    origin: Optional[str] = None
    spec: Optional[str] = None
    unit: Optional[str] = None
    price_per_unit: Optional[int] = None
    stock_quantity: Optional[int] = None
    min_order_qty: Optional[int] = None
    status: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None


class ProductResponse(BaseModel):
    id: UUID
    seller_id: UUID
    name: str
    category: str
    origin: Optional[str] = None
    spec: Optional[str] = None
    unit: str
    price_per_unit: int
    stock_quantity: int
    min_order_qty: Optional[int] = None
    status: str
    description: Optional[str] = None
    image_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
