from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin


class BuyerInventory(Base, SoftDeleteMixin):
    """구매자(BUYER) 재고 — 주문 COMPLETED 시 자동 누적되는 창고/매장 재고.

    - buyer_id × product_id 별 active row 1건 (partial unique index 보장)
    - quantity: 누적 수량 (>= 0). soft-delete 후 재누적은 새 row.
    - unit: 정렬/표기용 — 보통 product 의 마지막 unit 을 그대로 따라간다.
    - last_added_at: 가장 최근에 자동 누적된 시각 (KST 변환은 응답 단계에서).
    - notes: 사용자 메모 (창고 위치, 보관 방법 등).
    """

    __tablename__ = "buyer_inventories"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="buyer_inventories_quantity_nonneg"),
    )

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    buyer_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id"),
        nullable=False,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unit: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_added_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
