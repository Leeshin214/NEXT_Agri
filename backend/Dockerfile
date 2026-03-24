FROM python:3.11-slim

WORKDIR /app

# 시스템 의존성 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Python 의존성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 코드 복사
COPY app/ app/

# 비루트 사용자 생성 (보안)
RUN adduser --disabled-password --gecos "" appuser
USER appuser

# Railway가 PORT 환경변수를 자동 주입함
# 기본값 8000으로 설정
ENV PORT=8000

EXPOSE $PORT

# uvicorn 단일 워커로 실행 (async 기반이므로 단일 워커가 효율적)
# --workers 1: Railway 무료 플랜 메모리 제약 고려
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1
