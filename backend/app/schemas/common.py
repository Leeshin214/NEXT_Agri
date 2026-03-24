from typing import Generic, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class SuccessResponse(BaseModel, Generic[T]):
    data: T
    meta: Optional[dict] = None


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
    code: Optional[str] = None


class PaginationMeta(BaseModel):
    total: int
    page: int
    limit: int
    total_pages: int
