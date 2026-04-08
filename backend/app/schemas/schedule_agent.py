from pydantic import BaseModel
from typing import Optional


class ScheduleRecommendRequest(BaseModel):
    year: int
    month: int


class ScheduleRecommendation(BaseModel):
    recommended_date: str
    product_name: Optional[str] = None
    recommended_quantity: Optional[int] = None
    unit: Optional[str] = None
    reasoning: str


class ScheduleRecommendResponse(BaseModel):
    has_recommendation: bool
    recommendations: list[ScheduleRecommendation]
    message: str
