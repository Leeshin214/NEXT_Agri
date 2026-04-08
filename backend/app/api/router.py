from fastapi import APIRouter

from app.api.v1.ai_assistant import router as ai_router
from app.api.v1.calendar import router as calendar_router
from app.api.v1.chat import router as chat_router
from app.api.v1.orders import router as orders_router
from app.api.v1.partners import router as partners_router
from app.api.v1.products import router as products_router
from app.api.v1.schedule_agent import router as schedule_agent_router
from app.api.v1.users import router as users_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(users_router)
api_router.include_router(products_router)
api_router.include_router(orders_router)
api_router.include_router(partners_router)
api_router.include_router(calendar_router)
api_router.include_router(chat_router)
api_router.include_router(ai_router)
api_router.include_router(schedule_agent_router)
