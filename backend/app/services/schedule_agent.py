import asyncio
import json
from calendar import monthrange

from app.core.config import settings
from app.core.supabase import get_supabase_client
from app.schemas.schedule_agent import ScheduleRecommendResponse, ScheduleRecommendation


class ScheduleAgentService:
    def __init__(self):
        self._client = None  # lazy initialization

    @property
    def client(self):
        if self._client is None:
            self._client = get_supabase_client()
        return self._client

    async def build_schedule_context(
        self, user_id: str, role: str, year: int, month: int
    ) -> dict:
        # 해당 월의 시작/끝 날짜 계산
        _, last_day = monthrange(year, month)
        month_start = f"{year}-{month:02d}-01"
        month_end = f"{year}-{month:02d}-{last_day:02d}"

        # 1. calendar_events 조회 (calendar_events에는 deleted_at 없음 — SKILL_DB.md 확인)
        calendar_result = await asyncio.to_thread(
            lambda: self.client.table("calendar_events")
            .select("title, event_type, event_date, start_time, end_time")
            .eq("user_id", user_id)
            .gte("event_date", month_start)
            .lte("event_date", month_end)
            .limit(30)
            .execute()
        )
        calendar_events = calendar_result.data or []

        # 2. products 조회 (역할에 따라 분기)
        products = []
        if role == "SELLER":
            products_result = await asyncio.to_thread(
                lambda: self.client.table("products")
                .select("name, category, stock_quantity, unit, price_per_unit, min_order_qty, status")
                .eq("seller_id", user_id)
                .is_("deleted_at", "null")
                .limit(20)
                .execute()
            )
            products = products_result.data or []
        else:
            # BUYER: 최근 주문한 상품 정보 조회
            # orders → order_items → products 조인
            orders_result = await asyncio.to_thread(
                lambda: self.client.table("orders")
                .select("id")
                .eq("buyer_id", user_id)
                .is_("deleted_at", "null")
                .limit(20)
                .execute()
            )
            order_rows = orders_result.data or []
            if order_rows:
                order_ids = [row["id"] for row in order_rows]
                items_result = await asyncio.to_thread(
                    lambda: self.client.table("order_items")
                    .select("product_id")
                    .in_("order_id", order_ids)
                    .limit(20)
                    .execute()
                )
                item_rows = items_result.data or []
                if item_rows:
                    product_ids = list({row["product_id"] for row in item_rows})
                    products_result = await asyncio.to_thread(
                        lambda: self.client.table("products")
                        .select("name, category, stock_quantity, unit, price_per_unit, min_order_qty, status")
                        .in_("id", product_ids)
                        .is_("deleted_at", "null")
                        .limit(20)
                        .execute()
                    )
                    products = products_result.data or []

        # 3. orders 조회
        active_statuses = [
            "QUOTE_REQUESTED", "NEGOTIATING", "CONFIRMED", "PREPARING", "SHIPPING"
        ]
        id_col = "seller_id" if role == "SELLER" else "buyer_id"
        orders_result = await asyncio.to_thread(
            lambda: self.client.table("orders")
            .select("order_number, status, delivery_date, total_amount, notes")
            .eq(id_col, user_id)
            .in_("status", active_statuses)
            .is_("deleted_at", "null")
            .limit(15)
            .execute()
        )
        orders = orders_result.data or []

        has_data = bool(calendar_events or products or orders)

        return {
            "calendar_events": calendar_events,
            "products": products,
            "orders": orders,
            "has_data": has_data,
        }

    def _build_system_prompt(self, role: str, company_name: str) -> str:
        if role == "SELLER":
            return f"""당신은 AgriFlow 농산물 유통 플랫폼의 출하 일정 추천 AI입니다.

[역할]
판매자({company_name})의 출하/납품 일정을 최적화합니다.

[분석 기준]
1. 기존 캘린더 일정과 겹치지 않는 날짜 우선
2. 재고 수준이 충분한 상품 우선 (재고 부족/품절 품목 제외)
3. 미확정 주문의 납품 요청일 고려
4. 주말 피하기 (토/일)
5. 출하 간격이 너무 촘촘하지 않도록 분산

[응답 규칙]
- 반드시 아래 JSON 형식으로만 응답하세요
- reasoning은 반드시 한국어 1-2문장으로 작성
- 최대 3개까지 추천
- 데이터가 부족하면 has_recommendation을 false로 설정

[JSON 형식]
{{"has_recommendation": true, "recommendations": [{{"recommended_date": "YYYY-MM-DD", "product_name": "상품명", "recommended_quantity": 숫자, "unit": "단위", "reasoning": "추천 이유"}}], "message": "요약 메시지"}}"""
        else:
            return f"""당신은 AgriFlow 농산물 유통 플랫폼의 발주 일정 추천 AI입니다.

[역할]
구매자({company_name})의 발주/입고 일정을 최적화합니다.

[분석 기준]
1. 기존 캘린더 일정과 겹치지 않는 날짜 우선
2. 진행 중인 주문 납품일과 충분한 간격 유지
3. 견적 마감일 전에 발주 완료 권장
4. 주말 피하기 (토/일)
5. 입고 간격이 너무 촘촘하지 않도록 분산

[응답 규칙]
- 반드시 아래 JSON 형식으로만 응답하세요
- reasoning은 반드시 한국어 1-2문장으로 작성
- 최대 3개까지 추천
- 데이터가 부족하면 has_recommendation을 false로 설정

[JSON 형식]
{{"has_recommendation": true, "recommendations": [{{"recommended_date": "YYYY-MM-DD", "product_name": "상품명", "recommended_quantity": 숫자, "unit": "단위", "reasoning": "추천 이유"}}], "message": "요약 메시지"}}"""

    def _build_user_message(self, context: dict, year: int, month: int) -> str:
        # 캘린더 일정 포맷
        calendar_events = context.get("calendar_events", [])
        if calendar_events:
            calendar_lines = "\n".join(
                f"- {row.get('event_date', '')[-5:].replace('-', '/')} ({row.get('event_type', '')}) {row.get('title', '')}"
                for row in calendar_events
            )
        else:
            calendar_lines = "등록된 일정이 없습니다"

        # 상품/재고 현황 포맷
        products = context.get("products", [])
        if products:
            status_map = {
                "NORMAL": "정상",
                "LOW_STOCK": "재고부족",
                "OUT_OF_STOCK": "품절",
                "SCHEDULED": "입고예정",
            }
            product_lines = "\n".join(
                f"- {p.get('name', '')}: {p.get('stock_quantity', 0)}{p.get('unit', '')} "
                f"({status_map.get(p.get('status', ''), p.get('status', ''))}) / "
                f"단가 {p.get('price_per_unit', 0):,}원 / "
                f"최소주문 {p.get('min_order_qty', 1)}{p.get('unit', '')}"
                for p in products
            )
        else:
            product_lines = "등록된 상품이 없습니다"

        # 주문 현황 포맷
        orders = context.get("orders", [])
        if orders:
            status_map = {
                "QUOTE_REQUESTED": "견적요청",
                "NEGOTIATING": "협의중",
                "CONFIRMED": "확정",
                "PREPARING": "준비중",
                "SHIPPING": "배송중",
            }
            order_lines = "\n".join(
                f"- {o.get('order_number', '')} / "
                f"{status_map.get(o.get('status', ''), o.get('status', ''))} / "
                f"납품일 {str(o.get('delivery_date', '') or '')[-5:].replace('-', '/')} / "
                f"{(o.get('total_amount') or 0):,}원"
                for o in orders
            )
        else:
            order_lines = "진행 중인 주문이 없습니다"

        return (
            f"[현재 조회 기간] {year}년 {month}월\n\n"
            f"[캘린더 일정]\n{calendar_lines}\n\n"
            f"[상품/재고 현황]\n{product_lines}\n\n"
            f"[주문 현황]\n{order_lines}\n\n"
            f"위 데이터를 분석하여 {year}년 {month}월 최적 일정을 추천해주세요."
        )

    async def get_recommendation(
        self,
        user_id: str,
        role: str,
        company_name: str,
        year: int,
        month: int,
    ) -> ScheduleRecommendResponse:
        # 1. 컨텍스트 조회
        context = await self.build_schedule_context(user_id, role, year, month)

        # 2. 데이터 없으면 조기 반환
        if not context["has_data"]:
            return ScheduleRecommendResponse(
                has_recommendation=False,
                recommendations=[],
                message="추천할 일정이 없습니다. 캘린더 일정, 상품, 또는 주문 데이터가 필요합니다.",
            )

        # 3. OpenAI 호출
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            system_prompt = self._build_system_prompt(role, company_name)
            user_message = self._build_user_message(context, year, month)

            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=1024,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
            )

            raw = response.choices[0].message.content or "{}"
            parsed = json.loads(raw)

            # Pydantic 검증
            return ScheduleRecommendResponse(
                has_recommendation=parsed.get("has_recommendation", False),
                recommendations=[
                    ScheduleRecommendation(**item)
                    for item in parsed.get("recommendations", [])
                ],
                message=parsed.get("message", ""),
            )

        except Exception as e:
            return ScheduleRecommendResponse(
                has_recommendation=False,
                recommendations=[],
                message=f"일정 추천 중 오류가 발생했습니다: {str(e)}",
            )


schedule_agent = ScheduleAgentService()
