"""정기배송(Subscription) 서비스 레이어.

V1.5 Phase 1.
V1.6 — 양방향 승인 모델: 초기 status=PENDING, accept/reject 엔드포인트 추가.

핵심 메서드:
  - create_subscription           : subscriptions(PENDING) + items 다중 INSERT
  - accept_subscription           : PENDING → ACTIVE (요청자 본인은 수락 불가)
  - reject_subscription           : PENDING → REJECTED (이력 보존)
  - list_subscriptions            : 본인이 buyer 또는 seller 인 정기배송 모두
  - get_subscription              : 단일 + items + 상대방 user 임베딩
  - update_subscription           : 부분 수정 + status 변경 시 next_delivery_date 재계산
  - delete_subscription           : soft delete
  - generate_order_for_round      : 이번 회차 주문 생성 + calendar 이벤트 생성

트랜잭션 정책:
  supabase-py 는 단일 클라이언트에서 BEGIN/COMMIT 트랜잭션 제어가 약하다.
  → 본 서비스는 "best-effort + 실패 시 롤백 보상" 패턴을 사용한다.

  create_subscription:
    1) subscriptions INSERT
    2) subscription_items 다중 INSERT (실패 시 → subscriptions hard-delete 보상)

  generate_order_for_round:
    1) orders INSERT (subscription_id, subscription_round 포함)
    2) order_items 다중 INSERT (실패 시 → orders hard-delete 보상)
    3) calendar_events INSERT (실패해도 주문은 살림)
    4) subscription.next_delivery_date 갱신 (실패해도 주문은 살림 — 사용자 보고 후 수동 재시도)
"""

import asyncio
import math
import random
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status

from app.core.supabase import get_supabase_client
from app.schemas.common import PaginationMeta


# ===========================================
# 다음 회차 날짜 계산 헬퍼
# ===========================================
def compute_next_date(
    current: date,
    frequency: str,
    day_of_week: Optional[int] = None,
    day_of_month: Optional[int] = None,
) -> date:
    """현재 회차 기준 다음 회차 date 를 계산한다.

    - WEEKLY:   current + 7일
    - BIWEEKLY: current + 14일
    - MONTHLY:  다음 달 같은 일자. 1/31 → 2/28(또는 2/29 윤년) 처럼 월말로 clamp.
                day_of_month 가 명시되면 그 값을 우선, 아니면 current.day 사용.

    엣지 케이스:
      - MONTHLY + day_of_month=31 + 다음달이 30일까지 → 30일 (clamp)
      - MONTHLY + day_of_month=31 + 다음달이 28일까지(2월) → 28일
      - 12월 → 다음 해 1월

    raises:
      ValueError: 알 수 없는 frequency
    """
    if frequency == "WEEKLY":
        return current + timedelta(days=7)
    if frequency == "BIWEEKLY":
        return current + timedelta(days=14)
    if frequency == "MONTHLY":
        if current.month < 12:
            next_month = current.month + 1
            next_year = current.year
        else:
            next_month = 1
            next_year = current.year + 1
        last_day = monthrange(next_year, next_month)[1]
        target_day = day_of_month if day_of_month is not None else current.day
        target_day = min(target_day, last_day)
        return date(next_year, next_month, target_day)
    raise ValueError(f"Unknown frequency: {frequency}")


# ===========================================
# Supabase select 임베딩
# ===========================================
SUBSCRIPTION_SELECT_WITH_JOINS = (
    "*,"
    "items:subscription_items(*,product:products(name,deleted_at)),"
    "buyer:users!buyer_id(name,company_name),"
    "seller:users!seller_id(name,company_name)"
)


def _flatten_subscription_row(row: dict) -> dict:
    """PostgREST 임베딩 응답을 SubscriptionResponse 평탄 구조로 변환."""
    buyer = row.pop("buyer", None) or {}
    seller = row.pop("seller", None) or {}
    row["buyer_name"] = buyer.get("name")
    row["buyer_company"] = buyer.get("company_name")
    row["seller_name"] = seller.get("name")
    row["seller_company"] = seller.get("company_name")

    items = row.get("items") or []
    flat_items: list[dict] = []
    for item in items:
        product = item.pop("product", None) or {}
        # 상품이 soft-deleted 면 product_name None 으로 노출
        if product and not product.get("deleted_at"):
            item["product_name"] = product.get("name")
        else:
            item["product_name"] = None
        flat_items.append(item)
    row["items"] = flat_items
    return row


# ===========================================
# 서비스
# ===========================================
class SubscriptionService:
    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = get_supabase_client()
        return self._client

    @property
    def table(self):
        return self.client.table("subscriptions")

    @property
    def items_table(self):
        return self.client.table("subscription_items")

    @property
    def orders_table(self):
        return self.client.table("orders")

    @property
    def order_items_table(self):
        return self.client.table("order_items")

    @property
    def calendar_table(self):
        return self.client.table("calendar_events")

    # ===========================================
    # 권한 / 조회 헬퍼
    # ===========================================
    @staticmethod
    def _assert_participant(subscription: dict, user_id: str) -> str:
        """user_id 가 buyer/seller 중 하나인지 확인하고 역할 반환."""
        if subscription.get("buyer_id") == user_id:
            return "BUYER"
        if subscription.get("seller_id") == user_id:
            return "SELLER"
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    async def _get_subscription_or_404(self, subscription_id: UUID) -> dict:
        result = await asyncio.to_thread(
            lambda: self.table.select(SUBSCRIPTION_SELECT_WITH_JOINS)
            .eq("id", str(subscription_id))
            .is_("deleted_at", None)
            .execute()
        )
        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Subscription not found",
            )
        return _flatten_subscription_row(result.data[0])

    # ===========================================
    # CRUD
    # ===========================================
    async def list_subscriptions(
        self,
        *,
        user_id: UUID,
        status_filter: Optional[str] = None,
        partner_user_id: Optional[UUID] = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[dict], PaginationMeta]:
        """본인이 buyer 또는 seller 인 정기배송 모두."""
        user_id_str = str(user_id)
        # buyer_id == me OR seller_id == me
        # supabase-py 의 .or_() 는 PostgREST or 문법 사용
        query = (
            self.table.select(SUBSCRIPTION_SELECT_WITH_JOINS, count="exact")
            .is_("deleted_at", None)
            .or_(f"buyer_id.eq.{user_id_str},seller_id.eq.{user_id_str}")
        )

        if status_filter:
            query = query.eq("status", status_filter)

        # partner_user_id 필터 — 상대방 user 가 그 사용자인 정기배송만
        # (내가 buyer 면 seller_id == partner_user_id, 내가 seller 면 buyer_id == partner_user_id)
        if partner_user_id:
            partner_id_str = str(partner_user_id)
            query = query.or_(
                f"and(buyer_id.eq.{user_id_str},seller_id.eq.{partner_id_str}),"
                f"and(seller_id.eq.{user_id_str},buyer_id.eq.{partner_id_str})"
            )

        offset = (page - 1) * limit
        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)

        result = await asyncio.to_thread(lambda: query.execute())
        total = result.count or 0
        rows = [_flatten_subscription_row(row) for row in (result.data or [])]

        meta = PaginationMeta(
            total=total,
            page=page,
            limit=limit,
            total_pages=math.ceil(total / limit) if total > 0 else 0,
        )
        return rows, meta

    async def get_subscription(
        self, subscription_id: UUID, user_id: UUID
    ) -> dict:
        sub = await self._get_subscription_or_404(subscription_id)
        self._assert_participant(sub, str(user_id))
        return sub

    async def create_subscription(self, user_id: UUID, payload: dict) -> dict:
        """subscriptions INSERT + items 다중 INSERT.

        실패 시 보상: items INSERT 가 일부라도 실패하면 subscriptions row hard-delete.
        """
        user_id_str = str(user_id)
        items_payload: list[dict] = payload.pop("items", []) or []

        if not items_payload:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one item is required",
            )

        seller_id = str(payload["seller_id"])
        buyer_id = str(payload["buyer_id"])

        # 사용자가 당사자인지 확인
        if user_id_str not in (seller_id, buyer_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You must be either the buyer or the seller",
            )

        # 총액 계산
        total_amount = sum(int(i["quantity"]) * int(i["unit_price"]) for i in items_payload)

        # 첫 회차의 next_delivery_date = start_date
        start_date_value = payload.get("start_date")
        if start_date_value is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="start_date is required",
            )
        # mode="json" 으로 ISO 문자열일 수도 있고 date 객체일 수도 있음
        next_delivery_str = (
            start_date_value if isinstance(start_date_value, str) else start_date_value.isoformat()
        )

        # frequency 검증
        frequency = payload.get("frequency")
        if frequency not in ("WEEKLY", "BIWEEKLY", "MONTHLY"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid frequency: {frequency}",
            )

        # V1.6 — 양방향 승인 모델:
        #   초기 status='PENDING'. 상대(created_by != user)가 accept_subscription 호출 시 ACTIVE 전환.
        #   created_by 컬럼에 요청자 user_id 저장 → 수락 권한 판단용.
        sub_payload = {
            **payload,
            "seller_id": seller_id,
            "buyer_id": buyer_id,
            "next_delivery_date": next_delivery_str,
            "total_amount": total_amount,
            "status": "PENDING",
            "created_by": user_id_str,
        }
        if payload.get("partner_id"):
            sub_payload["partner_id"] = str(payload["partner_id"])

        # subscriptions INSERT
        result = await asyncio.to_thread(
            lambda: self.table.insert(sub_payload).execute()
        )
        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create subscription",
            )
        sub = result.data[0]
        sub_id = sub["id"]

        # subscription_items 다중 INSERT — 실패 시 보상 hard-delete
        try:
            for item in items_payload:
                item_payload = {
                    "subscription_id": sub_id,
                    "product_id": str(item["product_id"]),
                    "quantity": int(item["quantity"]),
                    "unit_price": int(item["unit_price"]),
                    "unit": str(item["unit"]),
                }
                await asyncio.to_thread(
                    lambda p=item_payload: self.items_table.insert(p).execute()
                )
        except Exception as e:
            # 보상 — subscriptions hard-delete (FK CASCADE 가 items 도 정리)
            try:
                await asyncio.to_thread(
                    lambda: self.table.delete().eq("id", sub_id).execute()
                )
            except Exception as rollback_err:
                print(
                    f"[subscription_service.create_subscription] rollback 실패 "
                    f"sub_id={sub_id}: {type(rollback_err).__name__}: {rollback_err}"
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to insert subscription items: {type(e).__name__}: {e}",
            )

        # 최종 row + items + 상대방 임베딩으로 반환
        return await self._get_subscription_or_404(UUID(sub_id))

    async def update_subscription(
        self, subscription_id: UUID, user_id: UUID, payload: dict
    ) -> dict:
        """부분 수정. status 변경 시 next_delivery_date 재계산.

        - PAUSED → ACTIVE: 오늘 이후 다음 회차로 재계산
                            (현재 next_delivery_date 가 과거면 다음 회차 계산 반복)
        - ACTIVE → PAUSED / ENDED / CANCELLED: 그대로 유지
        - frequency / day_of_week / day_of_month / start_date 변경 시도
          현재 status 가 ACTIVE 면 next_delivery_date 도 일관 재계산
        """
        sub = await self._get_subscription_or_404(subscription_id)
        self._assert_participant(sub, str(user_id))

        update_data = {k: v for k, v in payload.items() if v is not None}
        if not update_data:
            return sub

        # status 변경 시 next_delivery_date 재계산
        new_status = update_data.get("status")
        old_status = sub.get("status")

        # 변경될 (또는 유지될) 핵심 필드들
        eff_frequency = update_data.get("frequency") or sub.get("frequency")
        eff_dow = (
            update_data.get("day_of_week")
            if "day_of_week" in update_data
            else sub.get("day_of_week")
        )
        eff_dom = (
            update_data.get("day_of_month")
            if "day_of_month" in update_data
            else sub.get("day_of_month")
        )
        eff_status = new_status or old_status

        # PAUSED → ACTIVE 또는 ACTIVE 상태에서 frequency/dow/dom/start_date 변경 시
        # next_delivery_date 재계산
        recompute = False
        if new_status == "ACTIVE" and old_status == "PAUSED":
            recompute = True
        elif eff_status == "ACTIVE" and (
            "frequency" in update_data
            or "day_of_week" in update_data
            or "day_of_month" in update_data
            or "start_date" in update_data
        ):
            recompute = True

        if recompute and eff_frequency in ("WEEKLY", "BIWEEKLY", "MONTHLY"):
            # 오늘 기준 다음 회차 — 현재 next_delivery_date 또는 start_date 부터 시작해
            # 오늘 이후가 될 때까지 반복 계산.
            cur_str = (
                update_data.get("start_date")
                or sub.get("next_delivery_date")
                or sub.get("start_date")
            )
            if cur_str:
                # str ISO 또는 date 객체 모두 처리
                if isinstance(cur_str, str):
                    cursor = date.fromisoformat(cur_str[:10])
                elif isinstance(cur_str, date):
                    cursor = cur_str
                else:
                    cursor = date.today()
                today = date.today()
                # 안전한 회차 한도 (1회 PATCH 가 무한 루프 안 되도록)
                max_iter = 520  # 약 10년치 주간 회차
                iters = 0
                while cursor < today and iters < max_iter:
                    cursor = compute_next_date(
                        cursor, eff_frequency, eff_dow, eff_dom
                    )
                    iters += 1
                update_data["next_delivery_date"] = cursor.isoformat()

        # date 객체가 dict 에 들어왔으면 ISO 로
        for key in ("start_date", "end_date", "next_delivery_date"):
            value = update_data.get(key)
            if isinstance(value, date) and not isinstance(value, datetime):
                update_data[key] = value.isoformat()

        await asyncio.to_thread(
            lambda: self.table.update(update_data)
            .eq("id", str(subscription_id))
            .is_("deleted_at", None)
            .execute()
        )
        return await self._get_subscription_or_404(subscription_id)

    async def delete_subscription(
        self, subscription_id: UUID, user_id: UUID
    ) -> bool:
        """soft delete."""
        sub = await self._get_subscription_or_404(subscription_id)
        self._assert_participant(sub, str(user_id))

        deleted_at = datetime.now(timezone.utc).isoformat()
        result = await asyncio.to_thread(
            lambda: self.table.update({"deleted_at": deleted_at})
            .eq("id", str(subscription_id))
            .is_("deleted_at", None)
            .execute()
        )
        return bool(result.data)

    # ===========================================
    # V1.6 — 양방향 승인 모델 accept / reject
    # ===========================================
    async def accept_subscription(
        self, subscription_id: UUID, user_id: UUID
    ) -> dict:
        """정기배송 요청 수락.

        조건:
          - subscription 의 buyer 또는 seller 본인이어야 함 (당사자 검증)
          - status='PENDING' 이어야 함
          - created_by != user_id (요청자 본인은 수락 불가)
            * created_by 가 NULL 인 경우 (V1.5 이전 데이터) 는 당사자 누구나 수락 허용
        동작:
          - status='ACTIVE' 로 전환
          - next_delivery_date 를 start_date 또는 오늘 이후 첫 회차로 재설정
        """
        sub = await self._get_subscription_or_404(subscription_id)
        user_id_str = str(user_id)
        self._assert_participant(sub, user_id_str)

        if sub.get("status") != "PENDING":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"수락할 수 없는 상태입니다 (current: {sub.get('status')})",
            )

        created_by_value = sub.get("created_by")
        # created_by 가 있으면 요청자 본인은 수락 불가
        if created_by_value and str(created_by_value) == user_id_str:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="요청자 본인은 수락할 수 없습니다.",
            )

        # next_delivery_date 재계산 — start_date 부터 오늘 이후가 될 때까지
        frequency = sub.get("frequency")
        start_date_value = sub.get("start_date")
        cursor: Optional[date] = None
        if isinstance(start_date_value, str):
            cursor = date.fromisoformat(start_date_value[:10])
        elif isinstance(start_date_value, date):
            cursor = start_date_value

        next_delivery_str: Optional[str] = None
        if cursor and frequency in ("WEEKLY", "BIWEEKLY", "MONTHLY"):
            today = date.today()
            max_iter = 520  # 약 10년치 주간 회차 — 무한 루프 차단
            iters = 0
            while cursor < today and iters < max_iter:
                cursor = compute_next_date(
                    cursor,
                    frequency,
                    sub.get("day_of_week"),
                    sub.get("day_of_month"),
                )
                iters += 1
            next_delivery_str = cursor.isoformat()

        update_payload: dict = {"status": "ACTIVE"}
        if next_delivery_str:
            update_payload["next_delivery_date"] = next_delivery_str

        await asyncio.to_thread(
            lambda: self.table.update(update_payload)
            .eq("id", str(subscription_id))
            .is_("deleted_at", None)
            .execute()
        )
        return await self._get_subscription_or_404(subscription_id)

    async def reject_subscription(
        self, subscription_id: UUID, user_id: UUID
    ) -> dict:
        """정기배송 요청 거절.

        조건:
          - subscription 의 buyer 또는 seller 본인이어야 함 (당사자 검증)
          - status='PENDING' 이어야 함
          - created_by != user_id (요청자 본인은 거절 불가; created_by NULL 이면 허용)
        동작:
          - status='REJECTED' 로 전환 (이력 보존; soft-delete 와 별도)
        """
        sub = await self._get_subscription_or_404(subscription_id)
        user_id_str = str(user_id)
        self._assert_participant(sub, user_id_str)

        if sub.get("status") != "PENDING":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"거절할 수 없는 상태입니다 (current: {sub.get('status')})",
            )

        created_by_value = sub.get("created_by")
        if created_by_value and str(created_by_value) == user_id_str:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="요청자 본인은 거절할 수 없습니다.",
            )

        await asyncio.to_thread(
            lambda: self.table.update({"status": "REJECTED"})
            .eq("id", str(subscription_id))
            .is_("deleted_at", None)
            .execute()
        )
        return await self._get_subscription_or_404(subscription_id)

    # ===========================================
    # 회차 주문 생성
    # ===========================================
    def _generate_order_number(self) -> str:
        # ORD-{YYYYMMDD}-{4자리 랜덤} — order_service 와 동일 패턴
        date_str = datetime.now().strftime("%Y%m%d")
        rand_suffix = str(random.randint(1000, 9999))
        return f"ORD-{date_str}-{rand_suffix}"

    async def _next_subscription_round(self, subscription_id: str) -> int:
        """이 정기배송에 이미 생성된 주문 수 + 1."""
        result = await asyncio.to_thread(
            lambda: self.orders_table.select("id", count="exact")
            .eq("subscription_id", subscription_id)
            .is_("deleted_at", None)
            .execute()
        )
        return (result.count or 0) + 1

    async def generate_order_for_round(
        self, subscription_id: UUID, user_id: UUID
    ) -> dict:
        """이번 회차 주문 생성.

        스텝:
          1) subscription + items 조회 (당사자 검증)
          2) 회차 번호 계산 (기존 주문 수 + 1)
          3) orders INSERT (subscription_id, subscription_round)
          4) order_items 다중 INSERT (실패 시 → orders hard-delete 보상)
          5) calendar_events INSERT (양쪽 user; 실패해도 주문 살림)
          6) subscription.next_delivery_date 갱신 (실패해도 주문 살림)

        반환: 생성된 order dict
        """
        sub = await self._get_subscription_or_404(subscription_id)
        user_id_str = str(user_id)
        self._assert_participant(sub, user_id_str)

        if sub.get("status") != "ACTIVE":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Subscription is not ACTIVE (current: {sub.get('status')})",
            )

        items = sub.get("items") or []
        if not items:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Subscription has no items",
            )

        sub_id_str = str(sub["id"])
        delivery_date_value = sub.get("next_delivery_date")
        # next_delivery_date 가 str(ISO) 인지 date 인지 케이스 모두 처리
        if isinstance(delivery_date_value, date) and not isinstance(delivery_date_value, datetime):
            delivery_date_str = delivery_date_value.isoformat()
        else:
            delivery_date_str = (
                str(delivery_date_value)[:10] if delivery_date_value else None
            )

        # 회차 번호
        round_num = await self._next_subscription_round(sub_id_str)

        # 총액 (items 합산 — subscription.total_amount 와 일치 가정하지만 안전하게 재계산)
        total_amount = sum(
            int(i["quantity"]) * int(i["unit_price"]) for i in items
        )

        # orders INSERT — order_number UNIQUE 충돌 시 최대 3회 재시도
        order_payload_base = {
            "buyer_id": str(sub["buyer_id"]),
            "seller_id": str(sub["seller_id"]),
            "status": "CONFIRMED",
            "total_amount": total_amount,
            "delivery_date": delivery_date_str,
            "delivery_address": sub.get("delivery_address"),
            "notes": sub.get("notes"),
            "subscription_id": sub_id_str,
            "subscription_round": round_num,
        }

        from postgrest.exceptions import APIError as PostgrestAPIError

        order: Optional[dict] = None
        last_error: Optional[Exception] = None
        for _ in range(3):
            try:
                payload = {
                    **order_payload_base,
                    "order_number": self._generate_order_number(),
                }
                result = await asyncio.to_thread(
                    lambda p=payload: self.orders_table.insert(p).execute()
                )
                if result.data:
                    order = result.data[0]
                    break
            except PostgrestAPIError as e:
                err_code = getattr(e, "code", "") or ""
                err_msg = (getattr(e, "message", "") or "") + " " + str(e)
                if err_code == "23505" or "23505" in err_msg or "duplicate" in err_msg.lower():
                    last_error = e
                    continue
                raise

        if order is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="주문 번호 생성에 반복 실패했습니다. 잠시 후 다시 시도해주세요.",
            ) from last_error

        order_id = order["id"]

        # order_items 다중 INSERT — 실패 시 orders hard-delete 보상
        try:
            for item in items:
                item_payload = {
                    "order_id": order_id,
                    "product_id": str(item["product_id"]),
                    "quantity": int(item["quantity"]),
                    "unit_price": int(item["unit_price"]),
                    "subtotal": int(item["quantity"]) * int(item["unit_price"]),
                    "notes": None,
                }
                await asyncio.to_thread(
                    lambda p=item_payload: self.order_items_table.insert(p).execute()
                )
        except Exception as e:
            try:
                await asyncio.to_thread(
                    lambda: self.orders_table.delete().eq("id", order_id).execute()
                )
            except Exception as rollback_err:
                print(
                    f"[subscription_service.generate_order_for_round] rollback 실패 "
                    f"order_id={order_id}: {type(rollback_err).__name__}: {rollback_err}"
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to insert order items: {type(e).__name__}: {e}",
            )

        # calendar_events INSERT (양쪽 user; 실패해도 주문 살림)
        try:
            seller_id = str(sub["seller_id"])
            buyer_id = str(sub["buyer_id"])
            order_number = order.get("order_number") or order_id[:8]
            title = f"정기배송 #{round_num} - {order_number}"
            description_parts = [
                f"정기배송 {round_num}회차",
                f"금액: {int(total_amount):,}원",
            ]
            if delivery_date_str:
                description_parts.append(f"납기일: {delivery_date_str}")
            description = "\n".join(description_parts)

            for uid in (seller_id, buyer_id):
                if not uid:
                    continue
                try:
                    await asyncio.to_thread(
                        lambda u=uid: self.calendar_table.insert(
                            {
                                "user_id": u,
                                "order_id": order_id,
                                "title": title,
                                "event_type": "SHIPMENT",
                                "event_date": delivery_date_str,
                                "is_allday": True,
                                "description": description,
                            }
                        ).execute()
                    )
                except Exception as ce:
                    err_msg = str(ce).lower()
                    # partial unique index 충돌(23505)은 정상 race — 무시
                    if "23505" in err_msg or "duplicate" in err_msg:
                        continue
                    print(
                        f"[subscription_service.generate_order_for_round] "
                        f"calendar insert 실패 (무시): user={uid}, "
                        f"{type(ce).__name__}: {ce}"
                    )
        except Exception as e:
            print(
                f"[subscription_service.generate_order_for_round] "
                f"calendar 처리 전체 실패 (무시): {type(e).__name__}: {e}"
            )

        # subscription.next_delivery_date 갱신
        try:
            if delivery_date_str:
                cur = date.fromisoformat(delivery_date_str)
                next_d = compute_next_date(
                    cur,
                    sub["frequency"],
                    sub.get("day_of_week"),
                    sub.get("day_of_month"),
                )
                update_payload: dict = {"next_delivery_date": next_d.isoformat()}
                # end_date 가 있고 next_d 가 그 이후면 ENDED 처리
                end_date_value = sub.get("end_date")
                if end_date_value:
                    if isinstance(end_date_value, str):
                        end_d = date.fromisoformat(end_date_value[:10])
                    elif isinstance(end_date_value, date):
                        end_d = end_date_value
                    else:
                        end_d = None
                    if end_d and next_d > end_d:
                        update_payload["status"] = "ENDED"

                await asyncio.to_thread(
                    lambda: self.table.update(update_payload)
                    .eq("id", sub_id_str)
                    .is_("deleted_at", None)
                    .execute()
                )
        except Exception as e:
            print(
                f"[subscription_service.generate_order_for_round] "
                f"next_delivery_date 갱신 실패 (무시): {type(e).__name__}: {e}"
            )

        # 최신 order 다시 조회해 반환
        result = await asyncio.to_thread(
            lambda: self.orders_table.select("*")
            .eq("id", order_id)
            .single()
            .execute()
        )
        return result.data if result.data else order


subscription_service = SubscriptionService()
