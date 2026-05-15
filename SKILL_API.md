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

app = FastAPI(title="fresh link API", version="1.0.0")

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
    OPENAI_API_KEY: str = ""   # 백엔드 LLM 호출 전부 OpenAI 통일 (gpt-4o-mini)
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

# GET /products              - 상품 목록 (구매자: 전체 탐색, 판매자: 내 상품)
# GET /products/{id}         - 상품 상세 (단순, ProductResponse — 호환성 유지)
# GET /products/{id}/detail  - 상품 상세 페이지 전용 — 판매자 join + 거래 관계 + 같은 판매자 다른 상품 (B.1, 2026-05-04)
# POST /products             - 상품 등록 (판매자만)
# PATCH /products/{id}       - 상품 수정 (판매자만)
# DELETE /products/{id}      - 상품 삭제 (판매자만)

# GET /products/{id}/detail (B.1, 2026-05-04) — 상세 페이지 한 번 호출로 종합 컨텍스트
# 응답: SuccessResponse[ProductDetailResponse]
#   - ProductResponse 모든 필드
#   - seller_name / seller_company    : users 임베딩 join (판매자 담당자명/회사명)
#   - partner_relationship_status     : 현재 BUYER ↔ 판매자 partners.status
#                                        값: 'ACTIVE' | 'PENDING_OUTGOING' | 'PENDING_INCOMING'
#                                            | 'INACTIVE' | None (관계 없음)
#                                        SELLER 본인이 자기 상품 조회 시 None.
#   - previous_order_count            : BUYER ↔ 판매자 주문 총 건수 (CANCELLED/soft-deleted 제외)
#   - completed_order_count           : 그 중 status='COMPLETED' 만
#   - other_seller_products           : 같은 판매자의 다른 상품 (최대 4개, OUT_OF_STOCK 후순위)
#                                        ProductMinimal: {id, name, category, unit, price_per_unit,
#                                                          stock_quantity, status, image_url}
# 가드:
#   - 상품 없음 또는 soft-deleted → 404
#   - 판매자 자체가 soft-deleted 면 SELLER 본인 외엔 404 (구매자 노출 차단)
# 성능:
#   - SELLER 본인 조회: products+seller 1쿼리 + other_products 1쿼리 = 2쿼리
#   - BUYER 조회:       products+seller + partners + orders + other_products = 4쿼리
# 서비스: product_service.get_product_detail(product_id, *, current_user_id, current_user_role)

@router.get("", response_model=SuccessResponse[list[ProductResponse]])
async def list_products(
    category: Optional[str] = None,
    product_status: Optional[str] = None,
    seller_id: Optional[UUID] = None,
    search: Optional[str] = None,
    max_price: Optional[int] = Query(default=None, ge=0),  # price_per_unit <= max_price
    min_stock: Optional[int] = Query(default=None, ge=0),  # stock_quantity >= min_stock
    page: int = 1,
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
):
    ...

# list_products 서비스 시그니처 (product_service.py)
# async def list_products(
#     *, seller_id, category, status, search,
#     max_price: Optional[int] = None,   → .lte("price_per_unit", max_price)
#     min_stock: Optional[int] = None,   → .gte("stock_quantity", min_stock)
#     page, limit
# ) -> tuple[list[dict], PaginationMeta]
#
# 음수 방어: Query(ge=0) 으로 라우터에서 차단 (422 자동 반환)
# None 이면 해당 필터 생략 — 기존 동작 그대로 유지
```

### orders.py (주문/견적 API)
```python
router = APIRouter(prefix="/orders", tags=["orders"])

# GET /orders - 주문 목록 (역할에 따라 내 주문)
#   - order_status: Optional[str]                     단일 상태 (backward compat)
#   - status_in:    Optional[list[str]] = Query(None) 다중 상태 — ?status_in=A&status_in=B
#   - partner_user_id: Optional[UUID] = Query(None)   특정 거래처 user.id 양방향 OR 매칭
#                                                      (PM Report #8 작업 5 후속, 2026-04-28)
#                                                      (me==buyer AND counterpart==seller) OR
#                                                      (me==seller AND counterpart==buyer)
#                                                      → 전달 시 역할 기반 자동 필터를 대체.
#                                                      거래처 페이지 "최근 거래" 셀 클릭 시
#                                                      `?partner_user_id=...` 라우팅과 1:1 매칭.
#   - page:  Query(1, ge=1)
#   - limit: Query(20, ge=1, le=2000)                 프론트가 탭별 전체 조회 시 1000~2000 사용
#   둘 다 전달 시 status_in 이 우선 적용. 빈 list 면 단일 status fallback 안 함.
# GET /orders/{id} - 주문 상세
# POST /orders - 견적 요청 (구매자만)
# PATCH /orders/{id}/status - 상태 변경
# POST /orders/{id}/items - 아이템 추가

# 협상 (counter-offer) — 가격 협상
# POST   /orders/{id}/counter-offers                       제시
# POST   /orders/{id}/counter-offers/{offer_id}/accept     수락 → orders.total_amount 갱신
# POST   /orders/{id}/counter-offers/{offer_id}/reject     거절
# GET    /orders/{id}/counter-offers                       이력 (시간 역순)

# 납품일 변경 (delivery-date-changes) — 2026-04-29 신규
# POST   /orders/{id}/delivery-date-changes                            제시
# POST   /orders/{id}/delivery-date-changes/{change_id}/accept         수락 → orders.delivery_date 갱신
#                                                                       + calendar_events 재동기화
#                                                                       + DELIVERY_DATE_ACCEPTED 채팅 메시지
# POST   /orders/{id}/delivery-date-changes/{change_id}/reject         거절
# GET    /orders/{id}/delivery-date-changes                            이력 (시간 역순)
#
# Body (POST /delivery-date-changes):
#   { proposed_delivery_date: "YYYY-MM-DD",  # KST 기준 오늘 이상, 과거 → 422
#     notes: Optional[str] }
# Response: DeliveryDateChangeResponse {id, order_id, from_user_id, from_role,
#   proposed_delivery_date, notes, status (PENDING|ACCEPTED|REJECTED|SUPERSEDED),
#   responded_at, responded_by, created_at, updated_at,
#   from_user_name?, from_user_company?  # 동적 주입 (list 시 N+1 회피 일괄 join)}
#
# 가드:
#   - 주문 당사자(BUYER/SELLER)만 접근
#   - 제시: 주문 status ∈ {QUOTE_REQUESTED, NEGOTIATING, CONFIRMED} 만 허용
#           (PREPARING 이상은 출하 준비 단계라 차단)
#   - 본인이 제시한 PENDING 은 본인이 accept/reject 불가 (상대방만)
#   - 신규 제시 시 같은 주문의 이전 PENDING 은 모두 SUPERSEDED 마킹
#     + messages.metadata.status 도 동기화 (negotiation 패턴과 동일)

# 주문 취소 (PATCH /orders/{order_id}/cancel) — 2026-05-15 응답 지연 hotfix
#   - 가드: BUYER 는 QUOTE_REQUESTED/NEGOTIATING 만 직접 취소.
#           BUYER + CONFIRMED → cancel-request 사용 (403).
#           BUYER + PREPARING/SHIPPING → 403.
#           SELLER 는 모든 활성 상태 직접 취소.
#   - DB 업데이트 + calendar/chat soft-delete 후, BUYER 대체 거래처 탐색·AI 대화
#     히스토리 인서트·알림 emit 은 모두 fire-and-forget (asyncio.create_task) 로
#     `_trigger_alternative_partner_for_cancel` 한 번에 위임. 이전엔 인라인으로 await
#     직렬 처리되어 응답이 지연되고 클라이언트가 "Failed to fetch" (TypeError) 로
#     떨어졌다 — DB 는 이미 CANCELLED 였으므로 "취소는 되는데 에러는 떠 보이는" 증상.
#   - 함수 끝에 잘못 남아 있던 `if new_status == "CANCELLED":` 블록 (update_status
#     코드에서 복붙된 dead code) 제거 — NameError 로 500 응답되면 FastAPI 의
#     unhandled exception 핸들러가 CORS 헤더 없이 응답해 브라우저가 fetch 자체를
#     실패로 보고했다.
#
# 대체 거래처 자동 추천 (alternatives) — 2026-05-06 신규
# GET    /orders/{id}/alternatives
#   - 판매자가 활성 주문을 취소하면 백엔드가 fire-and-forget 으로 자동 생성하는
#     대체 판매자 + 자동 견적 결과 조회 (alternative_partner_recommendations 테이블).
#   - 권한: 본인이 buyer 인 주문만. 다른 buyer → 403, 없는 주문 → 404.
#   - 추천이 아직 없으면 data: null (404 가 아님) — 백그라운드 task 진행 중이거나
#     SELLER 가 취소한 게 아니거나 첫 item 정보가 부족한 케이스.
#   - 응답 구조: SuccessResponse<AlternativeRecommendationResponse | null>
#     {data: {id, cancelled_order_id, buyer_id, candidates: [...], reason, found_count, created_at}}
#   - candidates 의 각 원소: seller_id, seller_name, seller_company, product_id, product_name,
#       stock_quantity, price_per_unit, unit, trade_count, last_trade_date,
#       auto_order_id, auto_order_number, auto_order_error
```

### chat.py (채팅 API)
```python
router = APIRouter(prefix="/chat", tags=["chat"])

# GET    /chat/rooms                              - 내 채팅방 목록
# POST   /chat/rooms                              - 채팅방 생성 (or 기존 반환)
# GET    /chat/rooms/{room_id}/messages           - 메시지 목록 (limit, before)
# POST   /chat/rooms/{room_id}/messages           - 메시지 전송 (REST, 보통 WS 사용)
# POST   /chat/rooms/{room_id}/read               - 읽음 처리
# POST   /chat/rooms/{room_id}/counter-offer      - 채팅방 연결 주문에 협상가 제시
#
# AI 답장 초안 (US-1, 2026-05-03)
# POST   /chat/draft
#   Body: { room_id: UUID, instruction: str (1~500) }
#   응답: { data: { draft: str } }
#   특징:
#     - 메시지 DB INSERT 없음 — 초안 텍스트만 반환 (사용자 검토 후 직접 발송)
#     - 채팅방 참여자(seller/buyer) 검증 — 외부 호출 시 403
#     - 컨텍스트: chat_room.order_id 의 주문 상세 + 최근 20개 메시지 + 상대방 정보
#     - OpenAI gpt-4o-mini, temperature=0.5, max_tokens=400, 일반 응답 (스트리밍 X)
#     - 실패 시 502 + type(e).__name__ (네트워크/환각 빈 텍스트 모두 통일)
#   서비스 위치: app/services/draft_service.py (단일 함수 generate_chat_draft)
#   chat_node 와 별도 — send_chat_message 도구 미사용으로 의도치 않은 발송 차단
#
# AI 협상 의도 감지 (US-2, 2026-05-04)
# POST   /chat/rooms/{room_id}/messages — BackgroundTasks 로 detect 호출
#   기존 동작 유지(메시지 INSERT 응답 즉시) + add_task(process_message_for_negotiation)
#   감지 결과는 messages.metadata['draft_negotiation'] JSONB 에 저장,
#   confidence>=0.7 일 때만 저장 + WS push.
#
# PATCH  /chat/messages/{message_id}/dismiss-draft-negotiation
#   사용자가 [무시] 클릭 시 dismissed_at=NOW() 채움 (멱등).
#   응답: { data: { message_id, draft_negotiation: {...} } }
#   가드:
#     - 메시지 미존재 → 404
#     - sender_id != current_user → 403 (본인 메시지에만 dismiss 가능)
#     - draft_negotiation 자체 없음 → 404
#   주의: 5분 timeout 자동 dismiss 는 프론트가 시각적으로만 처리 (백엔드는 timeout 처리 X).
#   서비스 위치: app/services/negotiation_detection_service.py
#   - detect_negotiation_intent: OpenAI gpt-4o-mini, temperature=0,
#       response_format=json_object, max_tokens=200
#   - process_message_for_negotiation: 진입점 (BG task). 모든 예외 흡수 (chat 흐름 보호)
#   - dismiss_draft_negotiation: 본인 검증 + dismissed_at 멱등 갱신
#   ⚠️ 자동 등록 절대 X — 등록은 별도 사용자 [등록] 클릭으로 기존 propose_counter_offer 흐름.
```

### calendar.py (일정 API)
```python
router = APIRouter(prefix="/calendar", tags=["calendar"])

# GET /calendar - 일정 조회
#   - year:  Optional[int] = Query(None, ge=1900, le=2200)
#   - month: Optional[int] = Query(None, ge=1, le=12)
#   year + month 모두 전달 → 해당 월 범위 필터.
#   둘 중 하나라도 없으면 user 의 전체 active 일정 반환.
#   (프론트 우측 패널 "전체 일정" 리스트가 모든 월 일정을 받아오기 위함)
# POST /calendar - 일정 생성
# PATCH /calendar/{id} - 일정 수정
# DELETE /calendar/{id} - 일정 삭제 (soft)
#
# 응답 (CalendarEventResponse) — 정기배송 일정 식별 (2026-04-28):
#   - subscription_id: Optional[UUID]
#     정기배송으로 자동 등록된 일정이면 채워짐. 프론트는 이 필드로
#     "정기배송 일정" 라벨/배지/색상 구분 가능.
#   - subscription-only 일정은 order_id=NULL, event_type=SHIPMENT(seller)/DELIVERY(buyer)
#
# 호출 예:
#   GET /api/v1/calendar                      → 전체 active 일정
#   GET /api/v1/calendar?year=2026&month=5    → 5월만
#   GET /api/v1/calendar?year=2026            → year 만 단독은 전체 반환 (month 없으면 year 무시)
```

### ai_assistant.py (AI 도우미 API)
```python
router = APIRouter(prefix="/ai", tags=["ai"])

# POST /ai/chat          — 제거됨 (미사용 중복 엔드포인트, 2026-04-27)
# POST /ai/summarize-chat — 채팅 대화 AI 요약
# POST /ai/daily-summary  — 오늘의 업무 자동 요약
# POST /ai/agent/chat     — tool_use 오케스트레이터 기반 메인 AI 에이전트 (프론트 사용)
# GET  /ai/history        — AI 대화 히스토리 조회

# 메인 오케스트레이터: POST /api/v1/ai/agent/chat
# - agent_orchestrator.run() 호출 → tool 루프 → 최종 텍스트 반환
# - DB에서 최근 대화 10개 조회 후 history로 전달
# - 응답: SuccessResponse[dict] — { response: str, tools_used: list[str] }
# - 대화 후 ai_conversations 테이블에 저장 (prompt_type = ",".join(tools_used))
#
# 라우터(orchestrator_node) 분류 4종 (2026-04-29 CALENDAR 분기 추가):
#   - INVENTORY / ORDER → inventory_order_node (16개 tool)
#   - CALENDAR + DATA   → calendar_data_node (TOOLS_CALENDAR 2개만 노출)
#                          단순 일정 조회/등록 처리
#   - CALENDAR + REASON → calendar_reason_node
#                          schedule_agent.get_recommendation 으로 추천 데이터 받고 자연어화
#   - GENERAL           → response_node
# 라우터 응답 스키마 (LLM JSON):
#   {"intent":"INVENTORY"} | {"intent":"ORDER"}
#   {"intent":"CALENDAR","subtype":"DATA","target_year":YYYY,"target_month":MM}
#   {"intent":"CALENDAR","subtype":"REASON","target_year":YYYY,"target_month":MM}
#   {"intent":"GENERAL","response":"..."}
# target_year/month 폴백: DATA=이번달, REASON=다음달 (라우터 LLM 추출 실패 시 datetime.now() 기준)
# 응답 스키마는 변경 없음 — 프론트엔드 수정 불필요
```

### subscriptions.py (정기배송 API — V1.5 Phase 1, V1.6 양방향 승인 2026-04-28)
```python
router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])

# GET    /subscriptions                          - 내 정기배송 목록
#   - status: PENDING/ACTIVE/PAUSED/ENDED/CANCELLED/REJECTED (Query alias)
#   - partner_user_id: UUID — 이 거래처와의 정기배송만
#   - page, limit (le=2000)
# GET    /subscriptions/{id}                     - 단일 정기배송 (당사자만)
# POST   /subscriptions                          - 정기배송 생성 (buyer 또는 seller 본인만)
#                                                  → V1.6: 초기 status='PENDING', created_by=요청자
# POST   /subscriptions/{id}/accept              - V1.6 PENDING → ACTIVE
#   조건: 당사자 본인 + status=PENDING + created_by != user (NULL 이면 누구나 가능)
#   동작: status=ACTIVE 로 전환, next_delivery_date 를 start_date 또는 오늘 이후 첫 회차로 재설정
#   400 PENDING 아님 / 403 요청자 본인 또는 당사자 아님 / 404 없음
# POST   /subscriptions/{id}/reject              - V1.6 PENDING → REJECTED
#   조건: accept 와 동일 (당사자 + PENDING + created_by != user)
#   동작: status=REJECTED 전환 (이력 보존; soft-delete 와 별도)
# PATCH  /subscriptions/{id}                     - 부분 수정 (status 등; next_delivery_date 자동 재계산)
# DELETE /subscriptions/{id}                     - soft delete
# POST   /subscriptions/{id}/generate-order      - 이번 회차 주문 생성

# generate-order 동작:
#   1) orders INSERT (status=CONFIRMED, subscription_id, subscription_round 채워짐)
#   2) order_items 다중 INSERT (실패 시 orders hard-delete 보상)
#   3) calendar_events INSERT (양쪽 user; 실패해도 주문 살림)
#   4) subscription.next_delivery_date 갱신 (compute_next_date)
#   5) end_date 도달 시 status=ENDED 자동 전환
#   6) subscription-linked calendar_events UPSERT (새 next_delivery_date 로)

# 캘린더 자동 동기화 (2026-04-28, 마이그레이션 20260428000003):
#   - calendar_events.subscription_id 컬럼으로 정기배송 일정 식별.
#   - accept_subscription   : seller=SHIPMENT, buyer=DELIVERY 신규 INSERT
#   - update_subscription   : ACTIVE 면 next_delivery_date 동기화, 비활성이면 미래 일정 cleanup
#   - delete_subscription   : 미래 일정만 soft-delete (event_date >= today)
#   - reject_subscription   : 방어적 cleanup (정상 흐름엔 일정 없음)
#   - 멱등성: partial unique index uniq_calendar_events_active_subscription_user_date 로
#            (subscription_id, user_id, event_date) 활성 행 1개 보장.
#   - 실패 정책: best-effort, 주문/정기배송 자체는 막지 않고 로그만 남김.
```

### notifications.py (알림 API — 2026-04-29)
```python
router = APIRouter(prefix="/notifications", tags=["notifications"])

# 알림 type 화이트리스트 (notification_service.ALLOWED_NOTIFICATION_TYPES & DB CHECK):
#   NEW_MESSAGE, COUNTER_OFFER, OFFER_ACCEPTED, OFFER_REJECTED,
#   DELIVERY_DATE_CHANGE, DELIVERY_DATE_ACCEPTED, DELIVERY_DATE_REJECTED,
#   ORDER_STATUS, ALTERNATIVE_PARTNERS (2026-05-06)
#
# 🚨 알림 type 추가 시 4곳 모두 동기화 (한 곳이라도 빠지면 GET /notifications 가
#    ResponseValidationError 로 500 반환 — 종 아이콘 드롭다운이 통째로 안 뜸):
#   1) DB CHECK 제약: supabase/migrations/<날짜>_*.sql 에서 ALTER TABLE notifications
#      DROP/ADD CONSTRAINT notifications_type_check (DO $$ 블록 패턴).
#   2) backend/app/services/notification_service.py 의 ALLOWED_NOTIFICATION_TYPES set.
#   3) backend/app/schemas/notification.py 의 NotificationType Literal (응답 직렬화).
#   4) frontend/types/notification.ts 의 NotificationType union (TS 타입체크용).
#   추가로 frontend/components/layout/NotificationBell.tsx 의 NotificationIcon switch case
#   도 신규 type 마다 아이콘 매핑 추가 권장 (default 폴백 가능하지만 UX 일관성 위해).
#
# GET  /notifications?limit=30&only_unread=false
#   응답: SuccessResponse[list[NotificationResponse]] + meta {unread_count, total}
#   limit: 1~100 (기본 30)
#   only_unread=True 면 미읽음만 (total = unread_count)
# GET  /notifications/unread-count
#   응답: SuccessResponse[{unread_count: int}]  — 가벼운 폴링 fallback
# POST /notifications/{notification_id}/read
#   응답: SuccessResponse[NotificationResponse] — 단건 읽음
#   404: 본인 알림 아님 또는 존재하지 않음
# POST /notifications/read-all
#   응답: SuccessResponse[{updated: int}] — 미읽음 전체 읽음 처리

# 알림 타입 (DB CHECK 제약과 1:1):
#   NEW_MESSAGE, COUNTER_OFFER, OFFER_ACCEPTED, OFFER_REJECTED,
#   DELIVERY_DATE_CHANGE, DELIVERY_DATE_ACCEPTED, DELIVERY_DATE_REJECTED,
#   ORDER_STATUS

# INSERT 는 외부 노출 없음 — 서버 내부 emit 만 (notification_service.emit):
#   - order_service: 7곳 (counter offer 3 + delivery date 3 + status 1)
#   - chat_service.send_message: 1곳 (TEXT 만, sender == receiver skip)
# emit 시그니처:
#   await notification_service.emit(
#       user_id, type, title, body,
#       link_url=None, order_id=None, room_id=None,
#   )
# - 실패해도 호출처(주문/채팅) 흐름 막지 않음 (try/except + logger.error)
# - link_url 은 수신자 role 기준 (`/buyer/orders?id=...`, `/seller/chat?room_id=...`)
# - 자기 자신에게는 발송 안 함 (sender == receiver 면 skip)

# RLS: notifications_select_own / notifications_update_own (auth.uid() ↔ users.supabase_uid)
# INSERT 정책 미정의 → service_role 만 INSERT 가능 (anon/authenticated 차단).
# Supabase Realtime publication 등록 → 프론트가 종 아이콘 즉시 갱신 가능.
```

### partners.py (거래처 API — V1.6 양방향 승인 모델 2026-04-28)
```python
# V1.6 — 양방향 승인 모델
# POST  /partners                  - 거래처 등록 요청
#   동작: 본인 row(PENDING_OUTGOING) + 상대 row(PENDING_INCOMING) 두 row 동시 생성
#   응답: 본인 row(PENDING_OUTGOING) 만 partner_user 임베딩으로 반환
#   400  자기 자신을 거래처로 등록 시도
#   409  이미 (ACTIVE / PENDING_*) 상태로 row 존재
#   보상: 상대 row INSERT 실패 시 본인 row hard-delete (partial unique index 보존)
#
# POST  /partners/{id}/accept      - 받은 거래처 요청 수락 (status=PENDING_INCOMING 필수)
#   동작: 본인 row + 반대편 row 모두 status='ACTIVE' 전환
#   반대편 row 검색: (user_id=상대, partner_user_id=본인) 으로 lookup
#   400 상태가 PENDING_INCOMING 아님 / 404 row 없음
#
# POST  /partners/{id}/reject      - 받은 거래처 요청 거절 (status=PENDING_INCOMING 필수)
#   동작: 본인 row + 반대편 row 모두 soft-delete (deleted_at = NOW)
#   400 / 404 동일
#
# GET /partners/{id}/stats - 거래처 거래 통계
#   응답: PartnerStats
#     - total_orders:         CANCELLED/soft-deleted 제외 양방향 주문 수
#     - total_amount:         총 합계 금액
#     - last_order_date:      가장 최근 주문 일자 (YYYY-MM-DD)
#     - active_subscriptions: ACTIVE 정기배송 개수
#
# GET /partners?status=...
#   클라이언트는 status 파라미터로 그룹 조회:
#     - status=ACTIVE              : 활성 거래처
#     - status=PENDING_OUTGOING    : 본인이 보낸 요청
#     - status=PENDING_INCOMING    : 받은 요청
#     - status=INACTIVE            : 거래 종료
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
openai>=1.0.0
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

- **응답 표기 정책 — 상품·거래처·날짜·상태 메인, 주문번호는 부가 (2026-04-29)**: 주문/배송/일정 응답에서 LLM·프론트 모두 `[상품명] · [거래처명(company_name 우선, name 폴백)] · [날짜] · [상태]` 를 메인으로 쓰고 `order_number` 는 부가 식별자다. AGENT_BASE_SYSTEM 안의 `[응답 표기 정책 — 중요]` 단락 + `calendar_data_node` / `calendar_reason_node` 시스템 프롬프트 끝부분의 "응답 형식: 상품명 · 거래처명 · 날짜 · 상태 순으로 자연스럽게 풀어 쓰고, 주문번호는 끝에 작게 부연한다." 한 줄로 LLM 가이드. 백엔드 응답 데이터 측에서는 다음 3 위치에 buyer/seller/product 평탄화 필드를 일관 추가:
  - `CalendarEventResponse` (`schemas/calendar.py`) — `buyer_name/buyer_company/seller_name/seller_company` Optional 추가 (기존 `order_number/product_name/order_status` 옆).
  - `calendar_service._flatten_event_row` + `CALENDAR_SELECT_WITH_JOINS` + `list_events` 의 batch orders select — `users!buyer_id(name,company_name)` / `users!seller_id(name,company_name)` 임베딩 추가.
  - `agent_tools.get_orders` / `get_order_detail` / `get_calendar_events` — 동일 임베딩 + 평탄화. `get_orders` 는 `product_summary` ("{첫 상품명}" 또는 "{첫 상품명} 외 N건") + `items_count` 추가, `get_order_detail` items 는 `product_name`/`product_unit` 평탄화. LLM 토큰 절약을 위해 nested 임베딩 객체는 응답에서 제거하고 평탄화된 필드만 남긴다.

- **OpenAI 클라이언트는 `app/core/llm.py` 헬퍼 통해서만 생성 (2026-04-29 통일)**: 백엔드의 모든 LLM 호출은 `get_openai_client()` (비동기) / `get_openai_sync_client()` (동기) 싱글톤을 사용한다. 다른 모듈에서 `AsyncOpenAI` / `openai.OpenAI` 를 직접 인스턴스화하지 않는다. 이유는 (1) 키/모델 정책 변경 시 한 곳만 고치면 됨, (2) `AsyncOpenAI` 의 내부 httpx 클라이언트가 첫 호출 시점의 이벤트 루프에 바인딩되므로 lazy 싱글톤이 안전. 기본 모델은 `DEFAULT_MODEL = "gpt-4o-mini"`. requirements.txt 는 `openai>=1.0.0` 만 두고 `anthropic` 패키지는 더 이상 사용하지 않음.

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

- **LangGraph orchestrator `tool_round` 증분 규칙**: `inventory_order_node`(또는 동등한 tool 실행 노드)가 정상 완료 후 반환할 때도, 예외 경로에서 반환할 때도 `tool_round` 는 반드시 `+1` 씩만 증분해야 한다. `+MAX_TOOL_ROUNDS` 같은 값을 사용하면 첫 실행 직후 `tool_round >= 2` 조건이 충족되어 `validator_node`의 RETRY 분기가 절대 발동되지 않는다. 결과적으로 validator가 있어도 항상 FAILED로 단락되는 버그가 발생한다.
  ```python
  # 잘못된 패턴 — MAX_TOOL_ROUNDS(=3)만큼 한번에 증가 → RETRY 영구 불발
  "tool_round": state.get("tool_round", 0) + MAX_TOOL_ROUNDS,

  # 올바른 패턴 — 항상 1씩만 증가
  "tool_round": state.get("tool_round", 0) + 1,
  ```

- **시스템 프롬프트 합성 시 `.format()` 절대 금지 — `str.replace()` 명시 치환 사용**: AI 오케스트레이터의 시스템 프롬프트가 `BASE + ROLE_APPENDIX + FEW_SHOT_EXAMPLES` 형태로 합성될 때, APPENDIX 안의 `{seller_name}` 같은 LLM 안내용 중괄호와 FEW_SHOT_EXAMPLES 안의 JSON 예시 `{"name":"이철수",...}` 가 `.format()` 의 placeholder 로 잘못 인식되어 `KeyError: '"name"'` 발생. 결과적으로 모든 AI 호출이 catch 블록으로 떨어져 사용자에게는 "요청 처리 중 오류" 만 도달, AI 도우미 기능 완전 마비. 사용자 정보 치환은 반드시 명시적 `str.replace()` 함수로 처리한다.
  ```python
  def _render_agent_system(template: str, *, company_name: str, user_name: str, user_id: str) -> str:
      return (
          template
          .replace("{company_name}", company_name)
          .replace("{user_name}", user_name)
          .replace("{user_id}", user_id)
      )
  # 호출처: AGENT_SELLER_SYSTEM.format(...) 대신 _render_agent_system(AGENT_SELLER_SYSTEM, ...)
  ```
  검증 패턴: 스모크 테스트로 `_render_agent_system(AGENT_SELLER_SYSTEM, company_name='C', user_name='U', user_id='ID')` 가 KeyError 없이 동작하는지 확인.

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

- **AI 도구 모듈화 완료 — `agent/tools/<domain>.py` + ToolRegistry 자동 등록 (PR 0/1/2/3/4/5, 2026-05-05)**: 기존 `agent_tools.py` 단일 파일에 LLM 도구가 누적되어 한 도구 수정 시 다른 도구의 hunk 충돌이 빈번했다. 도메인별 분리 + `@tool` 데코레이터 자동 등록 인프라 도입 → PR 4 에서 `agent_tools.py` 완전 제거. PR 5 (2026-05-04) 에서 subscription 도메인에 `get_subscriptions` 추가 → 총 42 개 도구.
  ```
  backend/app/services/agent/
  ├── __init__.py        # TOOL_FUNCTION_MAP, TOOLS, TOOLS_CALENDAR, TOOLS_CHAT, INT_FIELDS 노출
  ├── _registry.py       # ToolRegistry (싱글톤), @tool 데코레이터, ToolEntry dataclass
  ├── _shared.py         # cross-domain 공통 helper (PR 4 완성)
  │                      # _UUID_PATTERN, _run_async_in_thread, _service_error_payload,
  │                      # _sync_calendar_events_for_order_id, _find_seller_by_name,
  │                      # _find_product_by_name, _deduct_seller_stock_for_order
  └── tools/
      ├── __init__.py    # 모든 도메인 모듈 import → @tool 등록 트리거
      ├── product.py     # 6 개 (inventory_order)
      ├── order.py       # 6 개 (inventory_order)
      ├── partner.py     # 7 개 (inventory_order)
      ├── subscription.py# 6 개 (inventory_order) — PR 4 incoming_requests, PR 5 get_subscriptions
      ├── negotiation.py # 6 개 (inventory_order)
      ├── user.py        # 4 개 (inventory_order)
      ├── calendar.py    # 4 개 (calendar)
      └── chat.py        # 3 개 (chat) + analyze_chat_consensus (LLM 도구 외)
  ```
  - 데코레이터 사용:
    ```python
    @tool(
        name="get_calendar_events",
        description="...",
        parameters={"type": "object", "properties": {...}, "required": [...]},
        groups=("calendar",),  # ("inventory_order",) | ("calendar",) | ("chat",)
        int_fields=frozenset({"quantity"}),  # tool_input 정수 변환 대상
    )
    def get_calendar_events(user_id: str, year: int, month: int) -> dict: ...
    ```
  - `ToolRegistry.schemas_for("calendar")` → OpenAI tool calling schema 리스트 (그룹별).
  - `ToolRegistry.function_map()` → name→callable 딕셔너리 (orchestrator `_execute_tool` 에서 사용).
  - 같은 이름 중복 등록 시 `RuntimeError("ToolRegistry 중복 등록 시도")` — 모듈 import 시점에 검증.
  - LangGraph 노드 분리: `inventory_order_node` 는 `TOOLS` (34), `calendar_data_node` 는 `TOOLS_CALENDAR` (4), `chat_node` 는 `TOOLS_CHAT` (3). 노드별 도구 격리로 `tool_choice="auto"` 단계에서 부적절한 도구 호출 방지.
  - **검증 명령**: `python3 -c "from app.services.agent import TOOL_FUNCTION_MAP, TOOLS, TOOLS_CALENDAR, TOOLS_CHAT; print(len(TOOL_FUNCTION_MAP), len(TOOLS), len(TOOLS_CALENDAR), len(TOOLS_CHAT))"` — 기대값 `41 34 4 3`.
  - **외부 import 경로**:
    - LLM 도구 호출은 `orchestrator` 가 `TOOL_FUNCTION_MAP` 으로 해결 → 직접 import 불필요.
    - `chat_ws.py` 의 직접 호출은 `from app.services.agent.tools.<domain> import <fn>` 사용 (예: `from app.services.agent.tools.calendar import create_calendar_event`).
    - cross-domain helper 직접 호출은 `from app.services.agent._shared import _UUID_PATTERN` 등.
    - **금지**: `from app.services.agent_tools import ...` (PR 4 이후 모듈 자체 부재 → ImportError).
  - **신규 도구 추가 패턴**: (1) 적절한 도메인 모듈 (`tools/<domain>.py`) 에 `@tool` 데코레이터 함수 추가, (2) cross-domain helper 가 필요하면 `from .._shared import ...` 로 lazy import (또는 module-level), (3) 신규 도메인 모듈 신설 시 `tools/__init__.py` 에 import 한 줄 추가, (4) 검증 — `python3 -m pytest tests/test_agent_registry.py tests/test_tools_smoke.py`. orchestrator.py 의 `TOOLS = ...` / `TOOLS_CALENDAR = ...` 는 자동 갱신.
  - **도구 카운트 하드코딩 — 두 테스트 동시 갱신 필수 (PR 5, 2026-05-04 발견)**: 도구 추가/삭제 시 hard-coded 총 카운트가 두 곳에 존재하므로 둘 다 갱신해야 한다. 한쪽만 갱신하면 smoke/registry 중 하나가 회귀로 실패한다.
    - `tests/test_agent_registry.py::test_domain_modules_register_42_tools` — `len(TOOL_FUNCTION_MAP)`, `len(TOOLS)`, `len(TOOLS_CALENDAR)`, `len(TOOLS_CHAT)` 4개 assert.
    - `tests/test_tools_smoke.py::test_total_registered_tool_count` + `test_groups_distribution` — 동일 4개 카운트.
    - 검증 — `/Users/l.s.h/workspace/NEXT_2026/web/backend/nextagri/bin/python -c "from app.services.agent import TOOL_FUNCTION_MAP, TOOLS, TOOLS_CALENDAR, TOOLS_CHAT; print(len(TOOL_FUNCTION_MAP), len(TOOLS), len(TOOLS_CALENDAR), len(TOOLS_CHAT))"` 로 실제 값 먼저 확인 후 두 파일 동시 수정.

- **agent 도구는 항상 sync — async service 호출 시 sync 재구현 (2026-05-04 partner 거래처 등록 도구 추가)**: `orchestrator._execute_tool` 은 `func(**tool_input)` 패턴으로 도구 함수를 호출한다 (await 없음). 따라서 `agent/tools/<domain>.py` 의 모든 도구는 동기 함수여야 한다. 만약 호출하고 싶은 비즈니스 로직이 `partner_service.create_partner` 처럼 `async def` 라면, 그 안의 핵심 로직(자기 자신 차단, 양방향 PENDING 두 row INSERT, 23505 처리, partner_user 임베딩)을 supabase 클라이언트 동기 호출 패턴으로 재구현하거나 `agent._shared._run_async_in_thread(coro_fn)` 으로 별도 thread 에서 실행한다. 검증된 패턴:
  ```python
  def request_partner_registration(user_id: str, target_user_id: str, note: Optional[str] = None) -> dict:
      # 1) 입력 검증 — UUID 형식 + 자기 자신 차단
      if user_id == target_user_id: return {"success": False, "error": "self_registration_not_allowed"}
      # 2) 상대방 존재 확인 — users.is_active=true AND deleted_at IS NULL
      # 3) 사전 active row 체크 — partial unique index (user_id, partner_user_id) WHERE deleted_at IS NULL
      #    → 23505 발생 전에 already_partner 응답
      # 4) 본인 row INSERT (PENDING_OUTGOING) — 23505 catch 시 already_partner
      # 5) 상대 row INSERT (PENDING_INCOMING) — 실패 시 본인 row hard-delete 보상
      # 6) partner_user 임베딩 응답 — _build_partner_response 헬퍼 재사용
  ```
  - 다중 매칭 시 confirmation 응답: `{"success": False, "needs_confirmation": True, "candidates": [{user_id, name, company_name, role}, ...]}` — `send_chat_message` 의 needs_confirmation 패턴과 일관. LLM 이 후보 리스트를 사용자에게 안내하고 사용자 응답 후 UUID 기반 도구로 다시 호출하도록 유도.
  - `_fix_id_params` 는 `user_id` 를 자동 강제 주입하므로 LLM 이 user_id 를 빠뜨려도 안전. `target_user_id` 는 LLM 이 보낸 값 보존 → 도구 내부 검증으로 invalid UUID/self/missing 을 각각 다른 error code 로 반환.

- **LangGraph 노드별 TOOLS 분리 시 시스템 프롬프트 동기화 필수 (2026-04-29 검증)**: 한 노드가 보유하던 도구를 별도 노드로 옮길 때(예: `inventory_order_node` 의 캘린더 도구 2개를 `calendar_data_node` 의 `TOOLS_CALENDAR` 로 이동), 도구 정의만 옮기고 원래 노드의 시스템 프롬프트를 그대로 두면 LLM 이 존재하지 않는 도구를 호출 시도해서 OpenAI API 가 tool 이름을 모른다고 거부하거나, 가이드와 실제 도구 노출이 어긋나 답변이 어색해진다. 반드시 다음 4 영역을 동시에 정리한다.
  - 시스템 프롬프트 안의 `[사용 가능한 도구]` 목록에서 옮긴 도구 이름 삭제
  - CASE 매트릭스에서 해당 도구 호출 케이스 통째 삭제 (CASE 번호 재정렬 권장)
  - FEW_SHOT_EXAMPLES 의 시나리오 예시에서 해당 도구 호출 라인 삭제 또는 시나리오 자체 삭제
  - "별도 분기로 라우팅된다" 한 줄을 추가해 LLM 이 옮긴 도구를 책임지지 않음을 명시
  검증: `grep -n "<도구이름>" orchestrator.py` 결과가 `TOOLS_<NEW>` 정의·새 노드 docstring·새 노드 시스템 프롬프트 외에 남으면 안 된다. 또한 백엔드 자동 sync(예: `_sync_calendar_events_for_order_id`) 가 이미 도구 호출을 대체하고 있다면 시스템 프롬프트에 "백엔드 자동 sync 처리" 한 줄을 남겨 LLM 이 직접 등록하지 않도록 명시.

### 주의사항 & 함정

- `security = HTTPBearer()` (기본값)로 두면 브라우저 CORS preflight가 전부 실패한다.
  반드시 `HTTPBearer(auto_error=False)` + `Optional[HTTPAuthorizationCredentials]` + None 가드 조합을 사용한다.

- `allow_origins`만 설정하면 `http://127.0.0.1:*` Origin은 매칭되지 않는다.
  `allow_origin_regex`를 함께 사용해야 localhost 변형 전체를 커버할 수 있다.

- **Response 스키마에서 `deleted_at` 누락 주의**: DB 테이블에 `deleted_at`이 정의되어 있어도 Pydantic Response 스키마에 빠지는 경우가 있다. soft delete를 지원하는 모든 테이블의 Response 스키마에는 `deleted_at: Optional[datetime] = None`을 반드시 포함해야 한다. `UserResponse`에서 이 실수가 발견되어 수정되었다.

- **Response 스키마 ↔ 운영 DB 컬럼 정합 점검 결과 (2026-04-27)**: 운영 Supabase 컬럼과 1:1 매칭되도록 보강 완료한 스키마:
  - `CalendarEventResponse` — `updated_at`, `deleted_at` 추가 (calendar_events 에 deleted_at 컬럼이 마이그레이션으로 추가됨)
  - `CalendarEventResponse` — `order_number: Optional[str]`, `product_name: Optional[str]`, `order_status: Optional[str]` 추가 (2026-04-27). DB 컬럼이 아니라 orders/products 임베딩 결과를 flatten 한 파생 필드. order_id 가 None 이거나 주문이 soft-delete 된 경우 세 필드 모두 None. `order_status` 는 calendar_events.event_type 이 ORDER 로 고정되어 프론트가 색상 구분을 못 하던 문제를 해결하기 위해 orders.status 값을 그대로 노출.
  - `OrderResponse`, `ProductResponse`, `PartnerResponse`, `MessageResponse` — `deleted_at` 추가
  - `ChatRoomResponse` — `updated_at` 추가. **2026-05-06 갱신**: 마이그레이션 `20260506000001_add_deleted_at_to_chat_rooms.sql` 로 `chat_rooms.deleted_at` 추가됨 → `ChatRoomResponse` 에도 `deleted_at: Optional[datetime] = None` 추가 권장 (현재 미적용 — `list_rooms` 가 이미 필터링해서 None 만 반환하므로 외부 노출은 무해하지만 정합 보강 시 추가).
  - `OrderItemResponse`, `AIConversationResponse` — updated_at/deleted_at 모두 없음 (운영 DB와 정합 — 변경 불필요)

- **Calendar list_events backfill 호출 절대 금지 — mutation 시점 sync 만 사용 (2026-04-27 N+1 폭주 수정)**: 한때 `list_events` 첫 줄에서 `_ensure_order_events_for_user(user_id)` 를 호출해 user 의 모든 주문에 대해 `order_service.sync_calendar_events_for_order_id` 를 순차 실행하는 backfill 패턴이 있었다. 결과:
  1. **N+1 폭주** — user 가 가진 주문 N 건마다 단건 sync (orders SELECT + calendar_events SELECT/INSERT/UPDATE 3~4 round-trip) 가 발생.
  2. **동시 connection 한도 초과** — 프론트가 month=4,5,6 세 번 동시 호출 시 sync 가 중첩되어 `httpx.ReadError: [Errno 35] Resource temporarily unavailable` 발생. try/except 로 무시되었지만 N×왕복 시간은 그대로 사용자에게 노출.
  3. **불필요** — `order_service` 의 모든 mutation (`create_order`, `update_status`, `update_order`, `cancel_order`, `submit_counter_offer`, `accept_counter_offer`) 과 `agent_tools.create_order`/`update_order_status` 가 이미 `_sync_calendar_events_for_order` 를 호출하고 있어 calendar_events 는 항상 최신 상태.

  올바른 패턴: **데이터 변경 시점에만 sync, 조회 시점에는 절대 sync 하지 않는다.** 조회는 `calendar_events` 를 그대로 신뢰하면 된다. 만약 미래에 일관성 깨짐이 발견되면 admin endpoint 또는 마이그레이션 스크립트로 1회성 backfill 을 돌리되, 일반 조회 hot path 에는 절대 backfill 을 끼워넣지 않는다.

  ```python
  # 잘못된 패턴 — 매 GET 마다 user 주문 N 건 sync → ReadError 폭주
  async def list_events(self, *, user_id, year, month):
      await self._ensure_order_events_for_user(user_id)  # 절대 금지
      ...

  # 올바른 패턴 — mutation 시점에만 sync, 조회는 select 만
  async def list_events(self, *, user_id, year, month):
      events = await asyncio.to_thread(lambda: self.table.select("*")...)
      ...
  ```

  - 적용 위치: `calendar_service.list_events` 에서 `_ensure_order_events_for_user` 호출 제거 + 메서드 자체 dead code 삭제 + `tests/test_calendar_order_backfill.py` 폐기 (2026-04-27).
  - 검증: 제거 후 `[calendar_service] order calendar sync failed ... ReadError` 로그 사라짐. `order_status='PREPARING'` 등 파생 필드 정상 반환 확인.

- **Calendar 응답 join — list_events batch 분리 + create/update 단일 round-trip (2026-04-27 회귀 수정)**: 초기에는 `calendar_events → orders → order_items → products` 3-depth 임베딩을 한 번의 select 로 처리했으나, 4개 테이블에 대한 RLS 정책이 누적 평가되어 list_events 가 느려지고, create/update 후 `_get_event_with_joins` 로 한 번 더 왕복하던 구조가 추가 지연 원인이었다. 두 가지를 함께 고친다.
  1. **list_events**: 3-depth 임베딩 제거 → calendar_events 만 단순 select 후, order_id 모아서 단일 `in_("id", order_ids)` 로 orders+items+products 를 batch 조회. 메모리에서 join 합성. RLS 평가가 calendar_events 에서 한 번, orders 에서 한 번 분리되어 3-depth 누적보다 빠름.
  2. **create_event / update_event**: supabase-py 2.11.0 에는 `.insert(...).select(...)` 체이닝 메서드가 없지만, `builder.params = builder.params.set("select", CALENDAR_SELECT_WITH_JOINS)` 로 query param 을 직접 주입하면 PostgREST 가 `Prefer: return=representation` + `?select=...` 조합으로 INSERT/UPDATE 응답을 임베딩 트리째 돌려준다 → 추가 round-trip 제거.

  ```python
  CALENDAR_SELECT_WITH_JOINS = (
      "*,"
      "order:orders!order_id("
      "order_number,status,deleted_at,"   # status 추가 → order_status 파생 필드
      "items:order_items(product:products(name,deleted_at))"
      ")"
  )

  def _flatten_event_row(row: dict) -> dict:
      order_payload = row.pop("order", None)
      row["order_number"] = None
      row["product_name"] = None
      row["order_status"] = None      # event_type=ORDER 고정이라 프론트 색상용
      if not order_payload or order_payload.get("deleted_at"):
          return row
      row["order_number"] = order_payload.get("order_number")
      row["order_status"] = order_payload.get("status")
      ...

  # create_event 핵심 — supabase-py 의 SyncQueryRequestBuilder.params 는 mutable
  # (라이브러리 내부에서도 self.params = self.params.add(...) 로 갱신함)
  builder = self.table.insert(payload)
  builder.params = builder.params.set("select", CALENDAR_SELECT_WITH_JOINS)
  result = await asyncio.to_thread(lambda: builder.execute())
  return _flatten_event_row(result.data[0])

  # list_events 핵심 — batch 조회로 3-depth 임베딩 회피
  events = self.table.select("*").eq(...).execute().data  # 1회
  order_ids = sorted({str(r["order_id"]) for r in events if r.get("order_id")})
  if order_ids:
      orders = (self.client.table("orders")
          .select("id,order_number,status,deleted_at,"
                  "items:order_items(product:products(name,deleted_at))")
          .in_("id", order_ids).execute().data)  # 1회
  ```
  - PostgREST 는 임베딩 자식 row 의 `deleted_at` 을 자동 필터하지 않으므로, flatten 단계에서 명시 검사 필요.
  - `order_status` 는 orders.status 값 그대로 노출 (`QUOTE_REQUESTED|NEGOTIATING|CONFIRMED|PREPARING|SHIPPING|COMPLETED|CANCELLED`). calendar_events.event_type 이 "ORDER" 로 고정되어 프론트가 단조로운 색만 칠하던 회귀를 해결.
  - 쿼리 횟수 비교 — list_events: 3-depth 임베딩 1회 → batch 2회(이벤트+주문). create/update: 2회(INSERT/UPDATE + 재조회) → 1회(임베딩 동봉).
  - 적용 위치: `calendar_service.list_events`, `create_event`, `update_event`, `_flatten_event_row`, `_attach_order_payload` (2026-04-27 회귀 수정).

- **Calendar list_events year/month Optional — 전체 일정 조회 지원 (2026-04-27)**: 프론트 우측 패널 "전체 일정" 리스트가 현재 월에 한정되어 다른 월 일정이 안 보이던 문제를 해결하기 위해 `year`, `month` 를 `Optional[int] = Query(None, ge=..., le=...)` 로 변경. **둘 다 있을 때만** 월 범위 필터를 적용하고, 그 외(둘 다 None / year 만 / month 만)는 전체 active 일정 반환. 단순화 원칙으로 연 단위 단독 조회는 미지원 — month 가 없으면 year 도 무시.
  ```python
  # 라우터
  @router.get("", response_model=...)
  async def list_events(
      current_user: dict = Depends(get_current_user),
      year: Optional[int] = Query(None, ge=1900, le=2200),
      month: Optional[int] = Query(None, ge=1, le=12),
  ):
      events = await calendar_service.list_events(
          user_id=current_user["id"], year=year, month=month,
      )
      return {"data": events}

  # 서비스 — 쿼리 빌더 분기
  async def list_events(self, *, user_id, year=None, month=None):
      base = (self.table.select("*")
              .eq("user_id", str(user_id))
              .is_("deleted_at", None))
      if year is not None and month is not None:
          start_date = f"{year}-{month:02d}-01"
          end_date = (f"{year+1}-01-01" if month == 12
                      else f"{year}-{month+1:02d}-01")
          base = base.gte("event_date", start_date).lt("event_date", end_date)
      events_result = await asyncio.to_thread(
          lambda: base.order("event_date").execute()
      )
  ```
  - **dedupe 안전망 유지**: 전체 조회로 전환해도 `(order_id, event_date)` 키 dedupe 가 그대로 작동해 race-잔존 중복을 흡수한다 (manual event 는 dedupe 제외).
  - **페이지네이션 미적용**: calendar_events 는 사용자당 수백 건 수준이고 orders batch 조회도 distinct order_ids 수만큼 1회뿐이라 페이지네이션/limit 보호 없이 처리. 운영 로그상 응답 크기 문제 없음.
  - **호출 예**:
    - `GET /api/v1/calendar` → 전체 active 일정
    - `GET /api/v1/calendar?year=2026&month=5` → 5월만
    - `GET /api/v1/calendar?year=2026` → year 만 단독은 month 가 없으므로 전체 반환
  - **함정**: `year is not None and month is not None` 으로 명시 체크해야 한다. truthy 체크(`if year and month`) 는 `month=0` 같은 경계값을 잘못 처리할 수 있지만, `Query(ge=1, le=12)` 로 0 이 422 반환되므로 결과는 동일. 그럼에도 명시 비교가 의도를 더 분명히 드러낸다.
  - 적용 위치: `app/api/v1/calendar.py:list_events`, `app/services/calendar_service.py:list_events` (2026-04-27).

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

- **PostgreSQL UNIQUE 위반(23505) → 500 방지 패턴**: supabase-py 의 INSERT/UPDATE 에서 unique_violation 발생 시 `postgrest.exceptions.APIError` 가 raw 로 raise → FastAPI 가 500 으로 노출된다. 사용자에게는 잘못된 입력이거나 동시성 문제이므로 409 로 변환해야 한다.
  ```python
  from postgrest.exceptions import APIError as PostgrestAPIError

  try:
      result = await asyncio.to_thread(lambda: self.table.insert(payload).execute())
  except PostgrestAPIError as e:
      err_code = getattr(e, "code", "") or ""
      err_msg = (getattr(e, "message", "") or "") + " " + str(e)
      if err_code == "23505" or "23505" in err_msg or "duplicate" in err_msg.lower():
          raise HTTPException(409, detail="이미 등록된 …") from e
      raise
  ```
  - `APIError` 의 attribute: `code` (PostgreSQL error code, "23505" 등), `message`, `hint`, `details`. raw dict 는 `_raw_error`.
  - 적용 위치: `partner_service.create_partner` (UNIQUE(user_id, partner_user_id))
  - 동일 패턴이지만 "재시도" 가 의미있는 경우(예: order_number 자동생성)는 except 블록에서 재시도 후 최종 실패 시 변환.

- **order_number UNIQUE 충돌 방어 패턴 — 랜덤 + 재시도**: `_generate_order_number` 가 `ORD-{YYYYMMDD}-{HHMMSS}` (시분초) 기반이면 동시 합의 자동 주문 (chat_ws._handle_consensus) 에서 같은 초 두 요청이 충돌해 23505 → 500. 두 단계로 방어:
  1. 패턴을 `ORD-{YYYYMMDD}-{random.randint(1000,9999)}` 로 통일
  2. INSERT 23505 catch → order_number 재생성 + 재시도 (max 3회). 그래도 실패 시 409 변환.
  ```python
  for attempt in range(3):
      payload = {**base_payload, "order_number": self._generate_order_number()}
      try:
          result = await asyncio.to_thread(lambda p=payload: self.orders.insert(p).execute())
          order = result.data[0]; break
      except PostgrestAPIError as e:
          if (e.code == "23505") or "duplicate" in str(e).lower():
              continue
          raise
  else:
      raise HTTPException(409, "주문 번호 생성 반복 실패")
  ```
  적용 위치: `order_service.create_order` 단일 진입점. 이전에는 `agent_tools.create_order` 가 직접 INSERT 하며 같은 패턴을 중복 구현했으나, 2026-05-04 부터 `order_service.create_order` 로 통합됨 (아래 auto_confirm 항목 참조).

- **`order_service.create_order` V2 정책 — 모든 신규 주문은 QUOTE_REQUESTED 로 시작 (2026-05-04 갱신)**: 가격이 일치해도 즉시 CONFIRMED 자동 진입을 제거. 판매자 검토 후 `update_status(CONFIRMED)` 시점에 재고 차감. `auto_confirm=True` 의 의미는 "단가 일치 시 즉시 확정" 이 아니라 "단가 차이가 있을 때 자동 협상(카운터오퍼) 발사" 로 좁혀짐. 라우터(POST /orders) 는 그대로 `auto_confirm=False` (기본) 로 호출해 UI 모달 흐름 유지.
  ```python
  async def create_order(self, buyer_id: UUID, data: dict, auto_confirm: bool = False) -> dict:
      # V2 (2026-05-04): initial_status = "QUOTE_REQUESTED" — 항상 동일.
      # auto_confirm=True 면 products.price_per_unit 일괄 조회 → 라인별 비교
      #   "MATCH"     — 모든 라인 unit_price >= price_per_unit
      #                  → QUOTE_REQUESTED INSERT + "주문 견적 도착" SYSTEM 메시지
      #                    (상품/단가/납품일 정리, 판매자 수락 대기)
      #   "NEGOTIATE" — 한 라인이라도 unit_price < price_per_unit
      #                  → QUOTE_REQUESTED INSERT + 자동 카운터오퍼 → NEGOTIATING 전환
      # auto_confirm=False (UI 모달 / API 직접 흐름)
      #   → QUOTE_REQUESTED INSERT + "새 견적 요청" SYSTEM 메시지
      #
      # 재고 차감은 update_status(CONFIRMED) 시점에 일어남 (create_order 본문에서 호출 X)
  ```
  - 호출처별 정책: 라우터 = `auto_confirm` 미전달(기본 False); `agent_tools.create_order` = `auto_confirm=True` 명시; chat_ws consensus = agent_tools 경유로 자동 적용.
  - `agent_tools.create_order` 는 자체 INSERT 하지 않고 `order_service.create_order(buyer_id, data, auto_confirm=True)` 로 위임. product_id UUID/이름 해석 + seller 소속 검증 로직만 유지.
  - 반환 dict 의 `auto_confirmed` 키는 V2 부터 항상 False (호환성용 키 유지). LLM 시스템 프롬프트는 status 값으로 분기.
  - NEGOTIATE 분기 자동 카운터오퍼 실패는 logger.error 만 + 주문은 QUOTE_REQUESTED 로 살아남음 (best-effort).
  - 마이그레이션 영향: SHA `76c7736` 의 즉시-확정/재고-차감 코드는 이번 변경으로 제거됨. 기존 INSERT 직후 재고 차감 검증 테스트는 update_status(CONFIRMED) 분기 검증으로 이전 필요.
  - 검증: AST 파싱 + venv import + Pydantic Required 검증 (`OrderCreate.delivery_date.is_required() == True`) + TOOLS schema required list 에 `delivery_date` 포함 확인.

- **`OrderCreate.delivery_date` Required (2026-05-04)**: V2 부터 모든 주문 생성 흐름에서 납품일 필수. POST /orders 라우터는 422 자동 반환, agent_tools.create_order 는 빈 값 가드 (`{"success": False, "error": "..."}`) 로 명시 차단, orchestrator TOOLS create_order required list 에 `delivery_date` 추가. chat_ws consensus 흐름은 이전부터 `_validate_consensus_extracted` 에서 필수 검증 중이라 변경 없음.

- **PostgREST 임베딩으로 N+1 제거 (2026-04-27 검증)**: orders 같은 부모 테이블 응답에 buyer/seller(users), items+product 정보를 함께 내려야 할 때, 서비스 안에서 N개의 자식 select 를 따로 부르는 대신 PostgREST 의 select 임베딩 한 번으로 처리한다. count="exact" 와 임베딩이 동시에 잘 동작한다 (HTTP 206 + content-range 헤더 정상).
  ```python
  ORDER_SELECT_WITH_JOINS = (
      "*,"
      "items:order_items(*,product:products(name,unit,category)),"
      "buyer:users!buyer_id(name,company_name),"      # column-alias FK embedding
      "seller:users!seller_id(name,company_name)"     # FK constraint 이름 명시 불필요
  )

  def _flatten_order_row(row: dict) -> dict:
      buyer = row.pop("buyer", None) or {}
      seller = row.pop("seller", None) or {}
      row["buyer_name"] = buyer.get("name")
      row["buyer_company"] = buyer.get("company_name")
      row["seller_name"] = seller.get("name")
      row["seller_company"] = seller.get("company_name")
      for item in (row.get("items") or []):
          product = item.pop("product", None) or {}
          item["product_name"] = product.get("name")
          item["product_unit"] = product.get("unit")
          item["product_category"] = product.get("category")
      return row
  ```
  - `users!buyer_id` 처럼 컬럼명을 alias 로 쓰면 PostgREST 가 FK constraint 이름(`orders_buyer_id_fkey`) 을 자동 추론한다 — `users!orders_buyer_id_fkey` 처럼 풀네임 쓸 필요 없음.
  - 응답에 새로 추가하는 join 필드는 모두 `Optional` 로 둔다. 사용자/상품이 soft-delete 된 경우 임베딩이 `None` 이 되므로.
  - 적용 위치: `OrderResponse.buyer_name/buyer_company/seller_name/seller_company`, `OrderItemResponse.product_name/product_unit/product_category` (2026-04-27).
  - 회귀 검증: `tests/e2e_orders_join_fields.py` — list_orders / get_order / create_order / update_order / update_status 결과의 join 필드가 모두 채워지는지 검증.

- **상태 전이 역할 가드 — `(current, new)` 페어별 화이트리스트 (2026-04-27 도메인 정책)**: 단일 `new_status` 키 기반 가드 (`{"CONFIRMED": "BUYER", "COMPLETED": "SELLER"}`) 는 `QUOTE_REQUESTED → CONFIRMED` 와 `NEGOTIATING → CONFIRMED` 를 구분 못 하고, 동일한 new_status 라도 출발 상태에 따라 허용 역할이 다른 도메인 규칙(예: SHIPPING → COMPLETED 는 양쪽, 다른 → COMPLETED 는 막혀야 하는 경우)을 표현하지 못한다. 페어 키로 매트릭스를 잡는다.
  ```python
  TRANSITION_ROLE_GUARD: dict[tuple[str, str], set[str]] = {
      ("QUOTE_REQUESTED", "CONFIRMED"):       {"BUYER", "SELLER"},
      ("NEGOTIATING",     "CONFIRMED"):       {"BUYER", "SELLER"},
      ("CONFIRMED",       "PREPARING"):       {"SELLER"},        # 출하 책임
      ("PREPARING",       "SHIPPING"):        {"SELLER"},
      ("SHIPPING",        "COMPLETED"):       {"BUYER", "SELLER"},  # 수령 확인
      # 모든 단계 → CANCELLED 는 양쪽 허용
      ("QUOTE_REQUESTED", "CANCELLED"):       {"BUYER", "SELLER"},
      ("NEGOTIATING",     "CANCELLED"):       {"BUYER", "SELLER"},
      ("CONFIRMED",       "CANCELLED"):       {"BUYER", "SELLER"},
      ("PREPARING",       "CANCELLED"):       {"BUYER", "SELLER"},
      ("NEGOTIATING",     "QUOTE_REQUESTED"): {"BUYER", "SELLER"},  # 협상 롤백
      ("QUOTE_REQUESTED", "NEGOTIATING"):     {"BUYER", "SELLER"},
  }
  # update_status 안에서:
  allowed_roles = TRANSITION_ROLE_GUARD.get((current_status, new_status), set())
  if actor_role not in allowed_roles:
      raise HTTPException(403, "권한이 없습니다")
  ```
  - 매트릭스에 등록되지 않은 페어는 자동으로 `set()` (어느 역할도 불가) — 화이트리스트 방식으로 방어적 디폴트.
  - 전이 자체의 합법성(`ALLOWED_TRANSITIONS`) 검증은 그대로 두고, 그 이후에 역할 가드를 페어 단위로 확인한다.
  - 주문 당사자(`buyer_id == user.id` or `seller_id == user.id`) 검증은 별도로 유지 — 외부인 차단.

- **soft delete 필터 누락 — 운영 결함 사전 점검 (2026-04-27)**: `update_*`, `list_*`, `mark_as_*` 등 모든 액션 쿼리에 `.is_("deleted_at", None)` 누락 여부를 표 형태로 점검한다. 누락 시 soft-deleted 행에 영향을 주는 행위가 가능해진다.
  - `order_service.update_status` — 추가 완료
  - `chat_service.list_messages` — 추가 완료
  - `chat_service.mark_as_read` — 추가 완료
  - `chat_service.list_rooms` — 상대방 user 의 deleted_at 별도 조회로 필터링 (임베디드 조인 deleted_at 자동 적용 안 함). 2026-05-06 부터 `chat_rooms.deleted_at` 자체 필터도 SELLER/BUYER 양쪽 분기에 추가됨 (주문 취소 시 cascade soft-delete 와 정합).
  - `chat_service.delete_room(room_id)` — 신규 메서드 (2026-05-06). `order_service.cancel_order` 에서 호출되어 취소된 주문의 채팅방을 soft-delete.
  - `ai_context.build_seller_context` / `build_buyer_context` — calendar_events 조회 추가 완료

- **calendar_events 동기화 — order×user 당 active 1개 불변 보장 (2026-04-27 중복 누적 버그 수정)**: `order_service._sync_calendar_events_for_order_sync` 의 기존 구현은 user_id 단위로 매번 서브쿼리를 돌렸지만, 같은 (order_id, user_id) 안에서 event_date 가 다른 잔존 row 를 정리하지 못했고 race condition 에도 취약했다. DB 의 partial unique index `uniq_calendar_events_active_order_user_date` (SKILL_DB.md 참조) 와 함께 동작하도록 다음 패턴으로 견고화한다.
  ```python
  def _sync_calendar_events_for_order_sync(self, order: dict) -> None:
      order_id_str = str(order["id"])
      if order.get("status") == "CANCELLED" or order.get("deleted_at"):
          self._soft_delete_calendar_events_for_order_sync(order_id_str)
          return

      user_ids = self._calendar_user_ids_for_order(order)  # buyer_id, seller_id
      payload_base = self._build_order_calendar_payload(order)
      target_event_date = payload_base["event_date"]
      deleted_at = datetime.now(timezone.utc).isoformat()

      # 1) 한 번의 쿼리로 이 주문의 모든 active calendar_events 조회
      existing = (self.calendar_events
          .select("id,user_id,event_date,deleted_at,updated_at,created_at")
          .eq("order_id", order_id_str).is_("deleted_at", None).execute().data or [])

      # 2) user_id 별로 그룹핑
      rows_by_user: dict[str, list[dict]] = {}
      for r in existing:
          rows_by_user.setdefault(str(r["user_id"]), []).append(r)

      for user_id in user_ids:
          user_rows = rows_by_user.get(user_id, [])
          # event_date 일치 여부로 분리 (date 객체 또는 ISO 문자열 양쪽 호환)
          matching, others = [], []
          for r in user_rows:
              rd = str(r.get("event_date"))[:10] if r.get("event_date") else None
              (matching if rd == target_event_date else others).append(r)

          primary_id = None
          if matching:
              # 가장 최신 row 보존 (updated_at DESC, created_at DESC)
              matching.sort(key=lambda r: (r.get("updated_at") or "",
                                            r.get("created_at") or ""), reverse=True)
              primary_id = str(matching[0]["id"])
              self.calendar_events.update(payload_base).eq("id", primary_id).execute()
              # matching 중 나머지(중복) soft-delete
              for dup in matching[1:]:
                  self.calendar_events.update({"deleted_at": deleted_at}).eq(
                      "id", str(dup["id"])).execute()

          # 다른 event_date 의 잔존 row 도 모두 soft-delete (납기일 변경 후 정리)
          for stale in others:
              self.calendar_events.update({"deleted_at": deleted_at}).eq(
                  "id", str(stale["id"])).execute()

          if primary_id is None:
              try:
                  self.calendar_events.insert({
                      **payload_base, "user_id": user_id, "order_id": order_id_str
                  }).execute()
              except PostgrestAPIError as e:
                  # partial unique index 충돌(23505) — 정상 race, 무시
                  if (getattr(e, "code", "") == "23505"
                      or "23505" in str(e) or "duplicate" in str(e).lower()):
                      continue
                  raise
  ```
  - **불변 조건**: 한 주문 × 한 user 당 active calendar_events 정확히 1개 (DB partial unique index 와 일치).
  - **list_events 안전망**: DB 가 정상이어도 미래 race 를 방어하기 위해 `calendar_service.list_events` 응답 직전에 `(order_id, event_date)` 키로 dedupe 추가 — manual event(order_id IS NULL) 는 dedupe 제외.
  - **검증 포인트**: 사용자 보고된 케이스("같은 5/15 일정 수십개")는 cleanup SQL (위 SKILL_DB.md A/B/C) 적용 + 새 sync 함수 + partial unique index 조합으로 재발 차단.

- **다중값 query 파라미터 — `Query(None)` + `list[T]` 패턴 (2026-04-27 검증)**: 사용자가 한 번의 요청으로 여러 상태/카테고리/ID 등을 필터링하고 싶을 때, FastAPI 는 `param: Optional[list[str]] = Query(None)` 로 선언하면 동일 키 반복(`?status_in=A&status_in=B&status_in=C`) 을 자동으로 list 로 파싱한다. supabase-py 의 `.in_("col", values)` 와 직접 연결된다. 단일값 backward compat 유지하려면 단일 파라미터(`order_status`) 와 다중 파라미터(`status_in`) 를 동시에 받고 `if status_in:` 으로 우선순위 분기.
  ```python
  # 라우터
  @router.get("", response_model=...)
  async def list_orders(
      order_status: Optional[str] = None,                    # 기존
      status_in: Optional[list[str]] = Query(None),          # 신규
      page: int = Query(1, ge=1),
      limit: int = Query(20, ge=1, le=2000),                 # 운영 안전 상한
  ):
      data, meta = await order_service.list_orders(
          status=order_status, status_in=status_in, ...
      )

  # 서비스
  async def list_orders(self, *, status=None, status_in=None, ...):
      query = self.orders.select(...)
      if status_in:                                          # 우선
          query = query.in_("status", status_in)
      elif status:                                           # fallback
          query = query.eq("status", status)
  ```
  - **함정 1**: 빈 `[]` 가 들어오면 `if status_in:` 이 False 가 되어 단일 status fallback 으로 빠진다. 빈 list 가 "필터 없음" 이 아닌 "결과 없음" 의미라면 `if status_in is not None` 으로 체크해야 한다. 우리 케이스는 빈 list 의미를 정의하지 않아 truthy 체크로 충분 (UI 가 항상 1개 이상 보냄).
  - **함정 2**: `limit` 상한이 작으면(`le=100` 등) 프론트가 모든 항목 조회를 위해 보내는 큰 limit 가 422 로 거부된다. 운영 안전을 위해 `le=2000` 권장 — 메모리/응답 시간 모두 수용 가능 범위.
  - 적용 위치: `orders.list_orders` (status_in 다중 상태 필터, 2026-04-27).
  - 사용 예: `/api/v1/orders?status_in=COMPLETED&status_in=CANCELLED&limit=2000`

- **`model_dump()` → supabase-py 직렬화 함정 — 반드시 `mode="json"` (2026-04-27 검증)**: Pydantic v2 의 기본 `model_dump()` 은 `date`, `datetime`, `UUID`, `time`, `Decimal` 같은 타입을 Python 객체 그대로 dict 에 담는다. 이 dict 를 supabase-py 의 `.insert()` / `.update()` 에 넘기면 내부 httpx 가 `json.dumps` 로 직렬화하다가 `TypeError: Object of type date is not JSON serializable` 로 500 폭발한다. 라우터에서 `model_dump()` 호출 시 반드시 `mode="json"` 플래그를 붙여 ISO 문자열/문자열로 변환된 dict 를 서비스에 전달한다.
  ```python
  # 잘못된 패턴 — date 가 그대로 dict 에 담겨 supabase 호출 시 TypeError
  data=data.model_dump()
  data=data.model_dump(exclude_unset=True)
  data=data.model_dump(exclude_none=True)

  # 올바른 패턴 — date → ISO, UUID → str, Decimal → str
  data=data.model_dump(mode="json")
  data=data.model_dump(exclude_unset=True, mode="json")
  data=data.model_dump(exclude_none=True, mode="json")
  ```
  - 적용 위치 (검증된 곳, 2026-04-27):
    - `orders.py` — `create_order`, `update_order`, `submit_counter_offer` (delivery_date: Optional[date], proposed_items 안의 product_id: UUID)
    - `calendar.py` — `create_event`, `update_event` (event_date: date, start_time/end_time: time, order_id: UUID)
    - `partners.py` — `create_partner`, `update_partner` (partner_user_id: UUID; create 측 필수)
    - `subscriptions.py` — `create_subscription`, `update_subscription` (start_date/end_date: date, seller_id/buyer_id/partner_id/items.product_id: UUID, 2026-04-28)
  - 일관성 원칙: 라우터에서 `data: Pydantic_Model` 을 받아 service 로 dict 를 넘기는 모든 핸들러는 무조건 `mode="json"`. UUID/date/datetime/time 필드가 없더라도 미래 스키마 추가 시 회귀 방지를 위해 일관성 유지.
  - 서비스 내부에서 직접 `datetime.now(timezone.utc)` 같은 객체를 dict 에 넣을 때는 반드시 `.isoformat()` 으로 변환 (예: `order_service.cancel_order` 의 `cancelled_at`).
  - 검증: `tests/e2e_orders_flow.py` — `delivery_date: "2026-05-15"` 가 포함된 견적 요청 → counter-offer → 상태 전환 → 취소까지 전 단계 통과 확인 (2026-04-27, ALL E2E STEPS PASSED).

- **정기배송 generate_order_for_round 트랜잭션 보상 패턴 (2026-04-28 검증)**: supabase-py 는 단일 클라이언트에서 BEGIN/COMMIT 트랜잭션 제어가 약하다 (PostgREST 가 stateless). 다단계 INSERT 가 필요한 경우 "성공한 부분을 hard-delete 로 보상 롤백" 패턴을 사용한다. 정합성 보장은 가능하지만 race condition 직후 짧은 순간 partial state 가 노출될 수 있어 두 가지를 함께 적용해야 한다.
  1. **순차 실행 + try/except 보상**: 부모 row 먼저 INSERT → 자식 row 들 INSERT. 자식 INSERT 가 어느 한 단계라도 실패하면 부모 row 를 hard-delete (FK CASCADE 가 자식 정리).
  2. **calendar / next_date 갱신은 best-effort**: 주문 자체는 1단계 + 2단계로 일관되게 보장하고, calendar 동기화나 subscription.next_delivery_date 갱신은 실패해도 주문을 살린다 (로그만 남김 — 사용자가 다음 주기에서 자연 회복 가능).
  ```python
  # subscription_service.generate_order_for_round 패턴
  # 1) orders INSERT (order_number UNIQUE 충돌 시 최대 3회 재시도)
  for _ in range(3):
      try:
          payload = {**base, "order_number": self._generate_order_number()}
          result = await asyncio.to_thread(lambda p=payload: self.orders_table.insert(p).execute())
          if result.data: order = result.data[0]; break
      except PostgrestAPIError as e:
          if "23505" in str(e): continue
          raise

  # 2) order_items 다중 INSERT — 실패 시 보상 hard-delete
  try:
      for item in items:
          await asyncio.to_thread(lambda p=item_payload: self.order_items_table.insert(p).execute())
  except Exception as e:
      try:
          await asyncio.to_thread(lambda: self.orders_table.delete().eq("id", order_id).execute())
      except Exception as rb:
          print(f"rollback 실패 order_id={order_id}")
      raise HTTPException(500, f"items insert 실패: {e}")

  # 3) calendar / next_date 는 best-effort (실패해도 raise 안 함, 로그만)
  ```
  - 적용 위치: `subscription_service.create_subscription` (subscriptions → subscription_items), `subscription_service.generate_order_for_round` (orders → order_items → calendar → next_date 갱신).
  - **검증 패턴**: e2e 테스트에서 의도적으로 자식 INSERT 가 실패하는 케이스를 만들어 부모 row 가 hard-delete 되었는지 확인. `select count(*) from subscriptions where deleted_at is null` 등으로 정합성 검증.

- **PostgREST `.or_()` 양방향 페어 쿼리 — `and(...)` 그룹핑 (2026-04-28 검증)**: 거래처 통계 / 정기배송 partner 필터처럼 "(buyer=A AND seller=B) OR (buyer=B AND seller=A)" 양방향 매칭을 한 번의 쿼리로 처리하려면 PostgREST 의 `or` 안에 `and(...)` 그룹을 둘 사용한다.
  ```python
  # 잘못된 패턴 — buyer 또는 seller 가 partner 인 모든 주문 (양방향 안 맞음)
  query.or_(f"buyer_id.eq.{partner_id},seller_id.eq.{partner_id}")

  # 올바른 패턴 — (me, partner) AND (partner, me) 페어만
  query.or_(
      f"and(buyer_id.eq.{user_id},seller_id.eq.{partner_id}),"
      f"and(seller_id.eq.{user_id},buyer_id.eq.{partner_id})"
  )
  ```
  - 적용 위치: `partner_service.get_stats` (orders + subscriptions 카운트), `subscription_service.list_subscriptions` (partner_user_id 필터, 2026-04-28).
  - **함정**: PostgREST 의 `or_()` 인자 문자열에 공백이 있으면 안 됨 (URL 인코딩 깨짐). 예시처럼 `,` 로만 구분.
  - **함정 2**: `and(...)` 안에서 sub-condition 은 같은 컬럼이 반복되면 안 된다. PostgREST 가 마지막 것만 적용함. 위 패턴은 컬럼이 다르므로 안전.

- **calendar.py route prefix `/calendar` ↔ subscriptions calendar_events 직접 INSERT 분리 (2026-04-28)**: `subscription_service.generate_order_for_round` 가 calendar_events 를 직접 INSERT 하는 이유는 calendar_service 가 user_id 인자를 self("내" 일정만)로 가정하고 있어 양쪽 user 에게 동시 생성하기 어렵기 때문. order_service 도 동일 패턴(`_sync_calendar_events_for_order_sync` 안에서 calendar_events 테이블 직접 사용)을 쓴다. 이 패턴 유지 시 주의:
  - `event_type='SHIPMENT'` 또는 `'ORDER'` 등 calendar_events.CHECK 제약과 일치해야 함.
  - DB 의 `uniq_calendar_events_active_order_user_date` partial unique index 와 충돌 시 23505 발생 가능 — try/except 로 무시 (정상 race).
  - manual event 만 다루는 calendar_service 와는 격리된 기능으로 본다.

- **함수 파라미터로 builtin shadow 금지 — `type`, `id`, `list`, `dict` 등 (2026-04-29 latent bug 수정)**: Python 함수 시그니처에서 builtin 식별자를 그대로 파라미터명으로 쓰면 함수 본문 안에서 해당 builtin 호출이 차단된다. 특히 except 핸들러에서 `type(e).__name__` 같이 에러 분류 패턴을 쓰는데 시그니처에 `type: str` 이 있으면 `TypeError: 'str' object is not callable` 이 발생해 INSERT 실패 시 로그 자체가 깨진다. **검증된 사례**: `notification_service.emit(..., type: str, ...)` 가 105 line 의 `type(e).__name__` 를 파괴 — `notification_type: str` 으로 rename 하여 해결. 호출처(`chat_service.py`, `order_service.py`)도 keyword arg 를 `notification_type=` 으로 일괄 변경. **체크리스트**:
  - 새 service 메서드 작성 시 파라미터명에 builtin 사용 금지 (`type` → `notification_type`/`event_type`/`message_type`, `id` → `resource_id`/`user_id`, `list` → `items`, `dict` → `payload`, `format` → `output_format`).
  - 기존 코드 리뷰 시: `def fn(..., type: str, ...)` 같은 시그니처를 grep 으로 발견하면 우선 수정 대상.
  - 로그 포맷 문자열 안의 `type=%s` 는 builtin 호출이 아니므로 문제 없음 — 시그니처 파라미터만 주의.

- **브랜드명 표기 정책 — `fresh link` (2026-05-03 리네이밍)**: 서비스 브랜드명은 기존 `AgriFlow` 에서 `fresh link` 로 전환됨. 백엔드에서 사용자에게 노출되는 텍스트(OpenAPI title, AI 시스템 프롬프트의 자기소개·예시·답변 템플릿)는 모두 `fresh link` 로 통일. 표기 규칙:
  - 기본: `fresh link` (소문자 + 띄어쓰기 한 칸)
  - 문장 시작 등 대문자가 자연스러운 곳에서만: `Fresh link`
  - **절대 바꾸지 말 것**: 코드 식별자(변수/함수/클래스/모듈/파일명), DB 테이블·컬럼명, 마이그레이션 파일명, 환경변수 키, import 경로, 패키지명, DB 이름(`DATABASE_URL` 의 `/agriflow`), Docker 서비스명 같은 **사용자 노출되지 않는 모든 식별자**. `.env` 의 DB 이름 변경은 운영 마이그레이션 비용 큼 → 보존.
  - **검증된 변경 위치 (5개 파일, 9개 라인)**: `app/core/config.py:34` PROJECT_NAME, `app/services/schedule_agent.py:114,135` 출하/발주 일정 추천 AI 자기소개, `app/services/orchestrator.py:657` 라우터 시스템 프롬프트, `:690` GENERAL 분류 예시 발화, `:891` AGENT_BASE_SYSTEM, `:1479,1686` 캘린더 도우미 시스템 프롬프트, `:1743` 채팅 비서 시스템 프롬프트.
  - **검증 절차**: 변경 후 `grep -rni "agriflow" backend/` → `.env` DB 이름 1건만 남으면 정상. 그 외 잔여가 있으면 코드 식별자가 맞는지 명시적으로 판단해야 한다.
