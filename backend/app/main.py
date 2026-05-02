import asyncio
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.api.router import api_router
from app.core.config import settings
from app.core.exceptions import http_exception_handler, validation_exception_handler
from app.websocket.chat_ws import router as ws_router
from app.core.supabase import get_supabase_client

# ─────────────────────────────────────────────
# 1. 스케줄러 함수 정의
# ─────────────────────────────────────────────
def sync_order_status_from_calendar():
    """매일 자정에 실행되어 오늘 일정에 맞춰 주문 상태를 자동 업데이트하는 함수"""
    print(f"🕒 [{datetime.now()}] 캘린더 일정 기반 주문 상태 자동 동기화 시작...")
    
    try:
        supabase = get_supabase_client()
        
        # 오늘 날짜 구하기
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        # 오늘 날짜로 등록된 '출하' 및 '배송' 일정 쫙 뽑아오기
        events_res = (
            supabase.table("calendar_events")
            .select("order_id, event_type")
            .eq("event_date", today_str)
            .in_("event_type", ["SHIPMENT", "DELIVERY"])
            .is_("deleted_at", None)
            .execute()
        )
        
        events = events_res.data or []
        if not events:
            print("💤 오늘 날짜로 처리할 출하/배송 일정이 없습니다.")
            return

        # 일정 성격에 맞춰서 주문 상태(Status) 매핑 및 업데이트
        success_count = 0
        for event in events:
            order_id = event.get("order_id")
            event_type = event.get("event_type")
            
            if not order_id:
                continue

            new_status = ""
            if event_type == "SHIPMENT":
                new_status = "PREPARING"  # 출하 일정 -> 출하준비
            elif event_type == "DELIVERY":
                new_status = "SHIPPING"   # 배송 일정 -> 배송중

            # Supabase 주문 테이블 업데이트
            if new_status:
                supabase.table("orders").update({"status": new_status}).eq("id", order_id).execute()
                print(f"✅ 주문 {order_id} 상태 자동 변경 완료 -> {new_status}")
                success_count += 1
                
        print(f"🎉 총 {success_count}건의 주문 상태가 성공적으로 동기화되었습니다.")
        
    except Exception as e:
        print(f"❌ 스케줄러 실행 중 오류 발생: {e}")

def start_scheduler():
    scheduler = AsyncIOScheduler()
    
    scheduler.add_job(sync_order_status_from_calendar, 'cron', hour=0, minute=1) 
    
    scheduler.start()

# ─────────────────────────────────────────────
# 2. FastAPI Lifespan (앱 시작/종료 시 실행)
# ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 서버 시작: 스케줄러를 가동합니다.")
    start_scheduler()
    yield
    print("🛑 서버 종료: 스케줄러를 중지합니다.")

# ─────────────────────────────────────────────
# 3. FastAPI 앱 초기화
# ─────────────────────────────────────────────
app = FastAPI(
    title=settings.PROJECT_NAME, 
    version="1.0.0", 
    lifespan=lifespan 
)

# ─────────────────────────────────────────────
# 4. 미들웨어 및 라우터 설정
# ─────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_origin_regex=(
        r"https?://(localhost|127\.0\.0\.1)(:\d+)?"
        r"|https://[a-zA-Z0-9-]+\.vercel\.app"
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 에러 핸들러
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)

# 라우터
app.include_router(api_router)
app.include_router(ws_router)

@app.get("/health")
async def health_check():
    return {"status": "ok"}