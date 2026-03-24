# AgriFlow

농산물 유통 B2B AI 플랫폼 — 판매자(공급자)와 구매자(바이어)를 연결하는 업무 웹플랫폼

## 주요 기능

- 거래처 관리 (판매자 ↔ 구매자 연결)
- 주문 / 견적 워크플로우
- 재고 및 출하 관리
- 실시간 채팅
- AI 업무 보조 (Claude API 기반)

## 기술 스택

| 영역 | 기술 |
|------|------|
| Frontend | Next.js 14 (App Router), TypeScript, Tailwind CSS, Zustand, React Query |
| Backend | FastAPI, SQLAlchemy, Pydantic v2, asyncpg |
| Database | Supabase (PostgreSQL 15) |
| Auth | Supabase Auth (JWT) |
| AI | Anthropic Claude API |
| Infra | Vercel (FE), Railway/Fly.io (BE), Redis |

## 프로젝트 구조

```
agriflow/
├── frontend/     # Next.js 14 App
├── backend/      # FastAPI App
└── supabase/     # DB 마이그레이션 & 설정
```

## 로컬 개발 환경

### Frontend
```bash
cd frontend
npm install
cp .env.local.example .env.local  # 환경 변수 설정
npm run dev
```

### Backend
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # 환경 변수 설정
uvicorn app.main:app --reload
```

## 환경 변수

### Frontend (`.env.local`)
```
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### Backend (`.env`)
```
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_JWT_SECRET=
ANTHROPIC_API_KEY=
REDIS_URL=redis://localhost:6379
DATABASE_URL=postgresql+asyncpg://...
```

## 브랜치 전략

- `main` — 프로덕션
- `develop` — 개발 통합 브랜치
- `feature/*` — 기능 개발
