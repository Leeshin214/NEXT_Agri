# AgriFlow Frontend — Vercel 배포 가이드

## 환경변수 목록 (Vercel 대시보드에서 설정)

| 변수명 | 값 | 설명 |
|--------|-----|------|
| `NEXT_PUBLIC_SUPABASE_URL` | `https://vcvpeagywpsrdjaprxqr.supabase.co` | Supabase 프로젝트 URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | `eyJ...` | Supabase anon key |
| `NEXT_PUBLIC_API_URL` | `https://your-backend.railway.app` | Railway 백엔드 URL |

> `.env.production.example` 파일을 참조해 값을 채운다.

---

## 방법 1: GitHub 연동 배포 (권장)

### 1단계 — GitHub에 푸시

```bash
git add .
git commit -m "feat: add vercel deployment config"
git push origin main
```

### 2단계 — Vercel 프로젝트 생성

1. [vercel.com/new](https://vercel.com/new) 접속
2. GitHub 레포지토리 선택
3. "Configure Project" 화면에서:
   - **Root Directory**: `frontend` 입력 (루트 `vercel.json`의 `rootDirectory` 설정과 동일)
   - Framework Preset: Next.js (자동 감지됨)
4. **Environment Variables** 섹션에서 위 표의 3개 변수 추가
5. **Deploy** 클릭

### 이후 배포

- `main` 브랜치에 푸시하면 자동 배포
- PR 생성 시 Preview URL 자동 생성

---

## 방법 2: Vercel CLI 배포

### 설치

```bash
npm install -g vercel
```

### 첫 배포 (프로젝트 연결)

```bash
cd /Users/l.s.h/workspace/NEXT_2026/web

# 루트 vercel.json이 rootDirectory: "frontend"를 지정하므로
# 루트에서 실행
vercel

# 대화형 프롬프트:
# - Set up and deploy? → Y
# - Which scope? → 본인 계정 선택
# - Link to existing project? → N (신규)
# - Project name → agriflow-frontend
# - In which directory is your code located? → ./ (루트 vercel.json 사용)
```

### 환경변수 설정 (CLI)

```bash
vercel env add NEXT_PUBLIC_SUPABASE_URL production
vercel env add NEXT_PUBLIC_SUPABASE_ANON_KEY production
vercel env add NEXT_PUBLIC_API_URL production
```

### 프로덕션 배포

```bash
vercel --prod
```

---

## 백엔드 Railway URL 연결

### Railway 배포 완료 후

1. Railway 대시보드에서 백엔드 서비스의 **Public Domain** 확인
   - 예: `https://agriflow-backend-production.up.railway.app`

2. Vercel 대시보드에서 환경변수 업데이트:
   - `NEXT_PUBLIC_API_URL` → Railway URL로 변경

3. Vercel에서 **Redeploy** 실행 (환경변수 반영)

### CLI로 업데이트하는 경우

```bash
# 기존 값 제거 후 재추가
vercel env rm NEXT_PUBLIC_API_URL production
vercel env add NEXT_PUBLIC_API_URL production
# 입력: https://agriflow-backend-production.up.railway.app

vercel --prod
```

---

## CORS 설정 주의

Railway 백엔드의 FastAPI에서 Vercel 도메인을 허용해야 한다.

```python
# backend/app/main.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://your-agriflow.vercel.app",   # Vercel 배포 URL
        "https://your-custom-domain.com",      # 커스텀 도메인 (있는 경우)
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## 파일 구조 참고

```
web/
├── vercel.json              ← 루트: rootDirectory: "frontend" 지정
└── frontend/
    ├── vercel.json          ← frontend 전용: framework, build 명령
    ├── .env.local           ← 로컬 개발용 (Git 제외, 수정 금지)
    ├── .env.local.example   ← 로컬 개발 템플릿
    └── .env.production.example  ← Vercel 환경변수 참조용 템플릿
```

---

## 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| 빌드 성공, API 호출 실패 | `NEXT_PUBLIC_API_URL` 미설정 | Vercel 환경변수 확인 후 Redeploy |
| Supabase 인증 오류 | `NEXT_PUBLIC_SUPABASE_ANON_KEY` 오타 | Supabase 대시보드 → Settings → API에서 재확인 |
| 이미지 로드 실패 | `next.config.js` remotePatterns 미적용 | `*.supabase.co` 패턴 이미 설정됨, Supabase Storage URL 형식 확인 |
| 404 on refresh | Next.js App Router는 기본적으로 처리됨 | `vercel.json`에 rewrites 불필요 |
