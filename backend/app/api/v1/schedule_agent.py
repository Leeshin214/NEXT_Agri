from fastapi import APIRouter, Depends

from app.dependencies import get_current_user
from app.schemas.common import SuccessResponse
from app.schemas.schedule_agent import ScheduleRecommendRequest, ScheduleRecommendResponse
from app.services.schedule_agent import schedule_agent

router = APIRouter(prefix="/schedule-agent", tags=["schedule-agent"])


@router.post("/recommend", response_model=SuccessResponse[ScheduleRecommendResponse])
async def recommend_schedule(
    request: ScheduleRecommendRequest,
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["id"])
    role = current_user["role"]
    company_name = current_user.get("company_name") or ""

    result = await schedule_agent.get_recommendation(
        user_id=user_id,
        role=role,
        company_name=company_name,
        year=request.year,
        month=request.month,
    )
    return {"data": result}
