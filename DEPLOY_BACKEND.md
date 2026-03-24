# AgriFlow Backend — Railway 배포 가이드

## 사전 준비

- Railway 계정: https://railway.app
- Railway CLI 설치: `npm install -g @railway/cli`
- Supabase 프로젝트 ref: `vcvpeagywpsrdjaprxqr`

---

## 1. Supabase connection pooler URL 확인

1. Supabase Dashboard → 프로젝트 선택
2. 좌측 메뉴 **Settings** → **Database**
3. **Connection string** 섹션에서 **URI** 탭 선택
4. **Connection pooler** 토글 활성화 (Transaction mode, port **6543**)
5. 표시된 URL 복사:
   ```
   postgresql://postgres.[project-ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres
   ```
6. `postgresql://` → `postgresql+asyncpg://` 로 변경하여 사용:
   ```
   postgresql+asyncpg://postgres.vcvpeagywpsrdjaprxqr:[password]@aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres
   ```

> Transaction mode(port 6543)를 사용해야 한다. Session mode(port 5432)는 서버리스 환경에서 연결 수 초과가 발생한다.

---

## 2. Railway 프로젝트 생성 및 배포

### 2-1. CLI 로그인 및 프로젝트 초기화

```bash
# Railway 로그인
railway login

# 백엔드 디렉토리로 이동
cd /Users/l.s.h/workspace/NEXT_2026/web/backend

# 새 Railway 프로젝트 생성 (또는 기존 프로젝트에 연결)
railway init

# 프로젝트 이름 입력: agriflow-backend
```

### 2-2. Redis addon 추가

```bash
# Railway Redis 플러그인 추가
railway add --plugin redis

# REDIS_URL은 Railway가 자동으로 환경변수로 주입함
# 별도 설정 불필요
```

### 2-3. 환경변수 설정

```bash
# 필수 환경변수를 Railway에 설정
railway variables set SUPABASE_URL=https://vcvpeagywpsrdjaprxqr.supabase.co
railway variables set SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
railway variables set SUPABASE_JWT_SECRET=your-jwt-secret
railway variables set DATABASE_URL=postgresql+asyncpg://postgres.vcvpeagywpsrdjaprxqr:[password]@aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres
railway variables set ANTHROPIC_API_KEY=sk-ant-...
railway variables set FRONTEND_URL=https://your-app.vercel.app
```

또는 Railway Dashboard → 프로젝트 → Variables 탭에서 직접 입력.

### 2-4. 배포 실행

```bash
# Dockerfile 기반으로 빌드 및 배포
railway up

# 배포 로그 확인
railway logs
```

### 2-5. 배포 URL 확인

```bash
# 배포된 서비스 URL 출력
railway domain

# 헬스체크 확인
curl https://[your-service].railway.app/health
# 응답: {"status": "ok"}
```

---

## 3. 필요한 환경변수 목록

| 변수명 | 설명 | 필수 |
|--------|------|------|
| `SUPABASE_URL` | Supabase 프로젝트 URL | 필수 |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase service_role 키 (RLS 우회) | 필수 |
| `SUPABASE_JWT_SECRET` | JWT 서명 검증용 secret | 필수 |
| `DATABASE_URL` | Supabase connection pooler asyncpg URL | 필수 |
| `ANTHROPIC_API_KEY` | Claude API 키 | 필수 |
| `REDIS_URL` | Railway Redis addon URL (자동 주입) | 필수 |
| `FRONTEND_URL` | Vercel 프론트엔드 URL (CORS 허용) | 권장 |
| `PORT` | 서버 포트 (Railway 자동 주입, 기본 8000) | 자동 |

---

## 4. Railway Redis Addon 추가 방법

### Dashboard에서 추가
1. Railway Dashboard → 프로젝트 선택
2. 우측 상단 **+ New** 클릭
3. **Database** → **Add Redis** 선택
4. Redis 서비스가 생성되고 `REDIS_URL` 환경변수가 자동으로 백엔드 서비스에 주입됨

### CLI에서 추가
```bash
railway add --plugin redis
```

> Redis addon을 추가하면 `REDIS_URL`이 자동 주입되므로 수동 설정 불필요.

---

## 5. Vercel 프론트엔드 연동

프론트엔드 Vercel 배포 후 아래 환경변수를 Vercel Dashboard에 추가:

```
NEXT_PUBLIC_API_URL=https://[your-service].railway.app
```

그리고 Railway 백엔드에 FRONTEND_URL 업데이트:

```bash
railway variables set FRONTEND_URL=https://[your-vercel-app].vercel.app
```

---

## 6. 배포 후 확인 사항

```bash
# 헬스체크
curl https://[your-service].railway.app/health

# API docs
open https://[your-service].railway.app/docs

# 로그 스트리밍
railway logs --tail
```

---

## 7. 트러블슈팅

### asyncpg PreparedStatementError
Supabase connection pooler(Transaction mode) 사용 시 prepared statement 관련 에러가 발생하면
`DATABASE_URL`이 `pooler.supabase.com`을 포함하는지 확인한다.
`database.py`에서 자동으로 `statement_cache_size=0`을 설정하므로 별도 조치 불필요.

### CORS 에러
`FRONTEND_URL` 환경변수가 정확한 Vercel URL로 설정되어 있는지 확인한다.
`*.vercel.app` 패턴은 모든 Vercel 프리뷰 배포를 자동 허용한다.

### DB 연결 실패
- Transaction mode port는 **6543** (Session mode 5432와 다름)
- `DATABASE_URL`에 `postgresql+asyncpg://` prefix 확인
- Supabase Dashboard → Settings → Database → Connection pooling 활성화 여부 확인
