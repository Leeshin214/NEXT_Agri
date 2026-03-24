from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.exceptions import http_exception_handler, validation_exception_handler

app = FastAPI(title=settings.PROJECT_NAME, version="1.0.0")

# CORS
# - allow_origins: 명시적 허용 목록 (localhost 개발 환경 + FRONTEND_URL 프로덕션)
# - allow_origin_regex:
#     개발: localhost/127.0.0.1 임의 포트 전체 허용
#     프로덕션: *.vercel.app 서브도메인 전체 허용 (프리뷰 배포 포함)
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


@app.get("/health")
async def health_check():
    return {"status": "ok"}
