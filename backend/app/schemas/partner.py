from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class PartnerCreate(BaseModel):
    partner_user_id: UUID
    nickname: Optional[str] = None
    notes: Optional[str] = None


class PartnerUpdate(BaseModel):
    nickname: Optional[str] = None
    status: Optional[str] = None
    is_favorite: Optional[bool] = None
    notes: Optional[str] = None


class PartnerResponse(BaseModel):
    id: UUID
    user_id: UUID
    partner_user_id: UUID
    nickname: Optional[str] = None
    status: str
    is_favorite: bool
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    # 조인된 거래처 정보
    partner_name: Optional[str] = None
    partner_company: Optional[str] = None
    partner_role: Optional[str] = None
    partner_phone: Optional[str] = None

    model_config = {"from_attributes": True}
