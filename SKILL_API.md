# SKILL_API.md — FastAPI Backend Agent

## 역할
FastAPI 기반 백엔드 API 서버를 구현한다.  
라우터, 서비스 레이어, Pydantic 스키마, 의존성 주입을 담당한다.

---

## 프로젝트 구조

```
backend/
├── app/
│   ├── api/
│   │   ├── v1/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py
│   │   │   ├── users.py
│   │   │   ├── products.py
│   │   │   ├── orders.py
│   │   │   ├── partners.py
│   │   │   ├── chat.py
│   │   │   ├── calendar.py
│   │   │   └── ai_assistant.py
│   │   └── router.py
│   ├── core/
│   │   ├── config.py       # Settings (pydantic-settings)
│   │   ├── security.py     # JWT 검증
│   │   └── supabase.py     # Supabase client
│   ├── models/             # SQLAlchemy ORM models
│   ├── schemas/            # Pydantic v2 schemas
│   ├── services/           # 비즈니스 로직
│   ├── dependencies.py     # FastAPI Depends
│   └── main.py
├── tests/
├── .env
└── requirements.txt
```

---

## 핵심 패턴

### 1. main.py 기본 구조
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.router import api_router
from app.core.config import settings

app = FastAPI(title="AgriFlow API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    # localhost, 127.0.0.1 임의 포트 전체 허용 (개발 환경 CORS preflight 400 방지)
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")
```

### 2. config.py (pydantic-settings)
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    SUPABASE_URL: str
    SUPABASE_SERVICE_ROLE_KEY: str
    SUPABASE_JWT_SECRET: str
    ANTHROPIC_API_KEY: str
    OPENAI_API_KEY: str = ""   # GPT 스케줄 에이전트용
    DATABASE_URL: str
    REDIS_URL: str = "redis://localhost:6379"
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    class Config:
        env_file = ".env"

settings = Settings()
```

### 3. 의존성 주입 (현재 로그인 사용자)
```python
# app/dependencies.py
import asyncio
from typing import Callable, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import verify_supabase_jwt
from app.core.supabase import get_supabase_client

# auto_error=False: OPTIONS preflight 요청에 Authorization 헤더가 없어도 403 차단 안 함
# credentials is None 체크를 get_current_user 안에서 직접 처리
security = HTTPBearer(auto_error=False)

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증이 필요합니다.",
        )
    payload = await verify_supabase_jwt(credentials.credentials)  # async 함수
    supabase_uid = payload.get("sub")

    if not supabase_uid:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    client = get_supabase_client()
    result = await asyncio.to_thread(
        lambda: client.table("users")
        .select("*")
        .eq("supabase_uid", supabase_uid)
        .single()
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="User not found")

    return result.data

# 역할 체크
def require_role(role: str) -> Callable:
    async def role_checker(current_user: dict = Depends(get_current_user)) -> dict:
        if current_user.get("role") != role:
            raise HTTPException(status_code=403, detail=f"Access denied. Required role: {role}")
        return current_user
    return role_checker

# 역할별 의존성 바로가기
require_seller = require_role("SELLER")
require_buyer  = require_role("BUYER")
require_admin  = require_role("ADMIN")
```

### 4. 표준 응답 포맷
```python
# app/schemas/common.py
from typing import Generic, TypeVar, Optional
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
```

---

## 각 API 엔드포인트 설계

### users.py (회원 API)
```python
router = APIRouter(prefix="/users", tags=["users"])

# GET /users/me          - 내 정보 조회
# PATCH /users/me        - 내 프로필 수정
# GET /users/search      - 회원 검색 (role 파라미터 Optional)
# GET /users/{id}/profile - 개별 공개 프로필 조회 (인증된 사용자라면 역할 무관하게 조회 가능)

# GET /users/search 파라미터
# - search: Optional[str]  — 이름·업체명·이메일 OR ilike
# - role: Optional[str]    — SELLER 또는 BUYER만 허용; 없으면 요청자 반대 역할로 fallback
# - page, limit: 페이지네이션
#
# role 유효성 검증은 라우터에서 수행, 서비스는 target_role을 직접 받음
_OPPOSITE_ROLE = {"SELLER": "BUYER", "BUYER": "SELLER"}  # 라우터 레벨 상수
_ALLOWED_SEARCH_ROLES = {"SELLER", "BUYER"}               # ADMIN 등 거부용

# role이 ADMIN 등 허용 외 값이면 400 반환:
# raise HTTPException(400, f"허용된 role 값은 SELLER 또는 BUYER입니다. 전달된 값: {role}")
```

### products.py (상품 API)
```python
router = APIRouter(prefix="/products", tags=["products"])

# GET /products - 상품 목록 (구매자: 전체 탐색, 판매자: 내 상품)
# GET /products/{id} - 상품 상세
# POST /products - 상품 등록 (판매자만)
# PATCH /products/{id} - 상품 수정 (판매자만)
# DELETE /products/{id} - 상품 삭제 (판매자만)

@router.get("", response_model=SuccessResponse[list[ProductResponse]])
async def list_products(
    category: Optional[str] = None,
    status: Optional[str] = None,
    seller_id: Optional[UUID] = None,
    page: int = 1,
    limit: int = 20,
    sort_by: str = "created_at",
    order: str = "desc",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    ...
```

### orders.py (주문/견적 API)
```python
router = APIRouter(prefix="/orders", tags=["orders"])

# GET /orders - 주문 목록 (역할에 따라 내 주문)
# GET /orders/{id} - 주문 상세
# POST /orders - 견적 요청 (구매자만)
# PATCH /orders/{id}/status - 상태 변경
# POST /orders/{id}/items - 아이템 추가
```

### schedule_agent.py (GPT 스케줄 조율 에이전트 API)
```python
router = APIRouter(prefix="/schedule-agent", tags=["schedule-agent"])

# POST /schedule-agent/recommend
# Request:  { year: int, month: int }
# Response: SuccessResponse[ScheduleRecommendResponse]
#   - has_recommendation: bool
#   - recommendations: list[ScheduleRecommendation]  (최대 3개)
#   - message: str
# 인증 필요 (get_current_user), 역할 무관 (SELLER/BUYER 모두 사용)
# 내부적으로 calendar_events, products, orders를 조회해 GPT-4o-mini에게 전달
# OPENAI_API_KEY 환경변수 필요
```

### ai_assistant.py (AI 도우미 API)
```python
router = APIRouter(prefix="/ai", tags=["ai"])

@router.post("/chat")
async def ai_chat(
    request: AIChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """스트리밍 AI 응답"""
    from anthropic import AsyncAnthropic
    client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    # 사용자 컨텍스트 조회 (최근 주문, 재고, 일정)
    context = await build_user_context(current_user, db)

    async def generate():
        async with client.messages.stream(
            model="claude-sonnet-4-5",
            max_tokens=1024,
            system=f"""당신은 농산물 유통업 B2B 플랫폼의 AI 업무 도우미입니다.
사용자는 {current_user.role}로 {current_user.company_name}에 근무합니다.
현재 컨텍스트: {context}
간결하고 실용적인 답변을 한국어로 제공하세요.""",
            messages=[{"role": "user", "content": request.prompt}]
        ) as stream:
            async for text in stream.text_stream:
                yield f"data: {text}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
```

---

## Pydantic 스키마 예시

```python
# app/schemas/product.py
from pydantic import BaseModel, UUID4
from typing import Optional
from datetime import datetime

class ProductCreate(BaseModel):
    name: str
    category: str
    origin: Optional[str] = None
    spec: Optional[str] = None
    unit: str
    price_per_unit: int
    stock_quantity: int = 0
    min_order_qty: int = 1
    description: Optional[str] = None

class ProductResponse(BaseModel):
    id: UUID4
    seller_id: UUID4
    name: str
    category: str
    origin: Optional[str]
    spec: Optional[str]
    unit: str
    price_per_unit: int
    stock_quantity: int
    status: str
    image_url: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True
```

---

## 에러 처리

```python
# app/core/exceptions.py
from fastapi import Request
from fastapi.responses import JSONResponse

async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail, "code": str(exc.status_code)}
    )

async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"error": "Validation failed", "detail": str(exc.errors())}
    )
```

---

## requirements.txt

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
python-dotenv==1.0.1
python-multipart==0.0.9
pyjwt[crypto]==2.10.1
httpx==0.28.1
supabase==2.11.0
sqlalchemy[asyncio]==2.0.36
asyncpg==0.30.0
pydantic==2.10.4
pydantic-settings==2.7.1
celery==5.4.0
redis==5.2.1
anthropic==0.42.0
openai>=1.58.0
pytest==8.3.4
pytest-asyncio==0.24.0
pytest-cov==6.0.0
```

---

## 작업 체크리스트

- [ ] main.py + CORS 설정
- [ ] config.py (환경변수 로드)
- [ ] SQLAlchemy models (CLAUDE.md 스키마 기반)
- [ ] Pydantic schemas (Request/Response 분리)
- [ ] dependencies.py (get_current_user, get_db)
- [ ] 각 라우터 파일 생성
- [ ] 서비스 레이어 분리 (router에서 비즈니스 로직 분리)
- [ ] 에러 핸들러 등록
- [ ] Alembic 마이그레이션 설정
- [ ] `/health` 엔드포인트 추가
- [ ] OpenAPI docs 확인 (`/docs`)

---

## 실전 발견 사항

> **agent 전용 기록 공간**: 실제 작업을 통해 검증된 패턴과 함정만 기록한다.
> 가설이나 일반적인 FastAPI 지식은 추가하지 않는다.

### 검증된 패턴

- **HTTPBearer(auto_error=False)**: CORS preflight(OPTIONS) 요청은 Authorization 헤더를 보내지 않는다.
  기본값 `auto_error=True`이면 FastAPI가 OPTIONS 요청을 바로 400/403으로 차단한다.
  `auto_error=False`로 설정하고, `get_current_user` 안에서 `credentials is None`을 체크해 401을 명시적으로 발생시키는 것이 올바른 패턴이다.

- **CORSMiddleware allow_origin_regex**: `allow_origins` 리스트는 정확한 문자열 매칭이다.
  `http://127.0.0.1:3000`은 `http://localhost:3000`과 다른 Origin으로 인식되어 preflight가 400을 반환한다.
  개발 환경에서 `localhost`/`127.0.0.1` 양쪽과 임의 포트를 모두 허용하려면 `allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?"`를 함께 설정한다.

- **Supabase JWT secret — base64 decode 금지**: Supabase GoTrue는 `jwt.SignedString([]byte(jwtSecret))`로 서명한다. 즉 secret 문자열을 UTF-8 bytes로 그대로 사용한다. PyJWT도 string 키를 UTF-8로 변환하므로 둘이 일치한다. `base64.b64decode(settings.SUPABASE_JWT_SECRET)`를 하면 secret이 달라져서 서명 검증이 항상 실패한다. `jwt.decode(token, settings.SUPABASE_JWT_SECRET, ...)` 형태로 string을 그대로 전달해야 한다.

- **JWT 디버그 로깅 패턴**: 401 원인 추적을 위해 `get_current_user`와 `verify_supabase_jwt`에 print 로그를 추가한다.
  ```python
  # dependencies.py
  if credentials is None:
      print("[AUTH] credentials is None → 401 (토큰 미전송)")
  print(f"[AUTH] token received: {credentials.credentials[:30]}...")

  # security.py
  except jwt.InvalidTokenError as e:
      print(f"[AUTH] JWT 검증 실패: {str(e)}")
  ```

- **"The specified alg value is not allowed" 에러**: `algorithms=["HS256"]`만 지정했을 때 Supabase가 HS512 토큰을 발급하면 이 에러가 발생한다. `algorithms=["HS256", "HS512"]`로 확장해야 한다. 에러 발생 시 `jwt.get_unverified_header(token)`으로 실제 `alg` 값을 먼저 출력해 원인을 파악한다.

- **ES256 토큰 — JWKS 공개 키 검증**: Supabase가 ES256(타원 곡선 비대칭) 알고리즘을 사용하면 대칭 키(`SUPABASE_JWT_SECRET`)로 검증이 불가하다. `{SUPABASE_URL}/auth/v1/.well-known/jwks.json` 에서 공개 키를 받아 `ECAlgorithm.from_jwk()`로 변환한 뒤 `algorithms=["ES256"]`으로 검증해야 한다. JWKS는 모듈 레벨 변수(`_jwks_cache`)에 캐시해 매 요청마다 HTTP 호출이 발생하지 않도록 한다. `pyjwt[crypto]` extras(cryptography 패키지)가 반드시 설치되어 있어야 EC 알고리즘을 사용할 수 있다.

- **verify_supabase_jwt async 전환**: JWKS 공개 키를 가져오는 `httpx.AsyncClient` 호출이 포함되므로 `verify_supabase_jwt`는 반드시 `async def`로 선언해야 한다. 이를 호출하는 `get_current_user`에서도 `await verify_supabase_jwt(...)`로 호출해야 한다.

- **OpenAI `tool_choice` — `tools` 없이 단독 사용 금지**: `tool_choice` 파라미터는 반드시 `tools` 파라미터와 함께 전달해야 한다. `tools` 없이 `tool_choice="none"` 또는 다른 값을 보내면 OpenAI API가 400 에러를 반환한다. 요약/정리 단계처럼 도구 호출이 필요 없는 단순 completion 요청에서는 `tool_choice` 파라미터 자체를 생략한다.
  ```python
  # 잘못된 패턴 — tools 없이 tool_choice 전달 → OpenAI 400
  response = await client.chat.completions.create(
      model=model,
      messages=messages,
      tool_choice="none",  # tools 파라미터가 없으므로 400 에러
  )

  # 올바른 패턴 — tool_choice 생략
  response = await client.chat.completions.create(
      model=model,
      messages=messages,
  )
  ```

### 주의사항 & 함정

- `security = HTTPBearer()` (기본값)로 두면 브라우저 CORS preflight가 전부 실패한다.
  반드시 `HTTPBearer(auto_error=False)` + `Optional[HTTPAuthorizationCredentials]` + None 가드 조합을 사용한다.

- `allow_origins`만 설정하면 `http://127.0.0.1:*` Origin은 매칭되지 않는다.
  `allow_origin_regex`를 함께 사용해야 localhost 변형 전체를 커버할 수 있다.

- **Response 스키마에서 `deleted_at` 누락 주의**: DB 테이블에 `deleted_at`이 정의되어 있어도 Pydantic Response 스키마에 빠지는 경우가 있다. soft delete를 지원하는 모든 테이블의 Response 스키마에는 `deleted_at: Optional[datetime] = None`을 반드시 포함해야 한다. `UserResponse`에서 이 실수가 발견되어 수정되었다.

- **모듈 임포트 시점 Supabase 클라이언트 생성 금지**: `services/` 모듈 하단에 `instance = MyClass()`와 같이 즉시 인스턴스화하면, CI 환경처럼 유효한 `SUPABASE_SERVICE_ROLE_KEY`가 없을 때 임포트 시점에 "Invalid API key" 오류가 발생한다. Supabase 클라이언트를 멤버로 가지는 클래스는 반드시 lazy initialization을 적용한다.
  ```python
  class MyService:
      def __init__(self):
          self._client = None  # 즉시 생성하지 않음

      @property
      def client(self):
          if self._client is None:
              self._client = get_supabase_client()
          return self._client
  ```

- **CI용 더미 Supabase 키는 JWT 형식 필수**: Supabase Python 클라이언트는 서비스 롤 키가 JWT 형식(3개 세그먼트, `.`으로 구분)인지 내부적으로 검증한다. `SUPABASE_SERVICE_ROLE_KEY: test-key`처럼 평문 문자열을 쓰면 클라이언트 초기화에서 오류가 발생한다. CI의 더미 값은 아래처럼 유효한 JWT 구조를 갖춰야 한다.
  ```yaml
  SUPABASE_SERVICE_ROLE_KEY: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRlc3QiLCJyb2xlIjoic2VydmljZV9yb2xlIiwiaWF0IjoxNjAwMDAwMDAwLCJleHAiOjk5OTk5OTk5OTl9.test-signature
  ```

- **pytest 테스트 인증 모킹 — dependency_overrides 필수**: `patch("app.dependencies.get_current_user", return_value=USER)`는 FastAPI 라우터가 이미 import한 함수 참조에 효과가 없고, `MagicMock`은 async가 아니라서 실제 요청이 401을 반환한다. FastAPI 의존성 모킹은 반드시 `app.dependency_overrides`를 사용한다.
  ```python
  # conftest.py — 올바른 패턴
  from app.dependencies import get_current_user
  from app.main import app

  @pytest.fixture
  def mock_seller_auth():
      app.dependency_overrides[get_current_user] = lambda: SELLER_USER
      yield SELLER_USER
      app.dependency_overrides.pop(get_current_user, None)
  ```

- **pytest-asyncio + async def 테스트 함수**: `asyncio_mode = auto`로 설정된 경우 `@pytest.mark.asyncio` 데코레이터 없이 `async def`로 선언하는 것만으로 비동기 테스트가 실행된다. `verify_supabase_jwt`처럼 `async def`인 함수를 동기 테스트(`def`)에서 호출하면 코루틴 객체가 반환되어 테스트가 실제로 실행되지 않는다. 반드시 `async def` + `await`를 사용한다.
  ```python
  # pytest.ini 필수 설정
  [pytest]
  asyncio_mode = auto
  asyncio_default_fixture_loop_scope = function  # DeprecationWarning 제거

  # 올바른 async 테스트 패턴
  async def test_valid_token():
      result = await verify_supabase_jwt(token)
      assert result["sub"] == "user-123"

  async def test_expired_token():
      with pytest.raises(HTTPException) as exc_info:
          await verify_supabase_jwt(token)  # pytest.raises 블록 안에서도 await 가능
      assert exc_info.value.status_code == 401
  ```

- **서비스 클래스 Supabase mock — 테이블 캐시 + lazy init 조합 필수**: 서비스 클래스의 `__init__`에서 즉시 `get_supabase_client()`를 호출하면, 모듈 레벨 인스턴스(`product_service = ProductService()`)가 테스트 mock fixture보다 먼저 실행되어 patch가 무효화된다. 두 가지를 함께 적용해야 한다.
  1. **Lazy init**: `_client = None` 으로 선언 후 property에서 lazy 생성
  2. **fixture에서 `_client` 직접 교체**: mock fixture에서 서비스 인스턴스의 `_client`를 직접 mock으로 교체하고, 테스트 종료 후 원래 값으로 복원
  ```python
  # services/product_service.py — lazy init 패턴
  class ProductService:
      def __init__(self):
          self._client = None

      @property
      def client(self):
          if self._client is None:
              self._client = get_supabase_client()
          return self._client

      @property
      def table(self):
          return self.client.table("products")

  # conftest.py — _client 직접 교체 패턴
  @pytest.fixture
  def mock_supabase():
      from app.services.product_service import product_service
      original = product_service._client
      product_service._client = mock_client
      yield mock_client
      product_service._client = original
  ```

- **Supabase mock 테이블 이름별 캐싱 필수**: `mock_client.table(name)` 이 호출마다 새 MagicMock을 반환하면, 테스트에서 `mock_supabase.table("products").execute.return_value = ...` 로 설정한 값이 서비스에서 `self.client.table("products")` 를 호출할 때 다른 객체를 받아 무효화된다. `table(name)` 은 이름별 dict 캐시로 동일 객체를 반환해야 한다.
  ```python
  _table_cache: dict = {}
  def mock_table(name):
      if name not in _table_cache:
          _table_cache[name] = make_table_mock()
      return _table_cache[name]
  mock_client.table = mock_table
  ```

- **Supabase `.single()` mock — data 타입 차이**: 실제 Supabase에서 `.single().execute().data` 는 dict(단일 행)를 반환하고, 일반 `.execute().data` 는 list를 반환한다. mock에서 이 차이를 반영하지 않으면 서비스 코드가 list를 dict로 접근하여 `TypeError` 가 발생한다. `single()` 이후에는 별도 execute_result를 사용하고 `data = None` (또는 dict)으로 초기화해야 한다.
  ```python
  # make_table_mock 안에서
  single_table = MagicMock()
  single_execute_result = MagicMock()
  single_execute_result.data = None  # dict 또는 None — 절대 list 아님
  single_table.execute.return_value = single_execute_result
  table.single.return_value = single_table

  # 테스트에서 단일 조회 결과를 설정할 때
  table.single.return_value.execute.return_value.data = SAMPLE_ORDER  # dict
  ```

- **`create_*` 서비스가 내부에서 `get_*` 재호출**: `create_order` 등 일부 서비스 메서드는 insert 후 `get_order(id)` 를 재호출해 최종 결과를 반환한다. `get_order` 는 `.single().execute()` 를 쓰므로, 테스트에서 `table.execute.return_value` (insert용 list) 와 `table.single.return_value.execute.return_value` (get용 dict) 를 모두 설정해야 한다.
  ```python
  table = mock_supabase.table("orders")
  table.execute.return_value.data = [SAMPLE_ORDER]           # insert용
  table.single.return_value.execute.return_value.data = SAMPLE_ORDER  # get용
  ```

- **테스트 SAMPLE 데이터는 Response 스키마 필드를 모두 포함**: Pydantic Response 스키마에 required 필드(예: `min_order_qty: int`)가 있으면 SAMPLE dict에도 해당 필드가 있어야 `ResponseValidationError` 없이 응답 직렬화가 성공한다. 스키마 변경 시 테스트 SAMPLE 데이터도 함께 업데이트해야 한다.
