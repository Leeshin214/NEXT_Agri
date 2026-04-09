from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr


class UserResponse(BaseModel):
    id: UUID
    supabase_uid: UUID
    email: str
    name: str
    role: str
    company_name: Optional[str] = None
    phone: Optional[str] = None
    profile_image: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class UserPublicProfile(BaseModel):
    """공개 프로필 — supabase_uid 미포함"""
    id: UUID
    name: str
    email: str
    role: str
    company_name: Optional[str] = None
    phone: Optional[str] = None
    profile_image: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    name: Optional[str] = None
    company_name: Optional[str] = None
    phone: Optional[str] = None
    profile_image: Optional[str] = None
