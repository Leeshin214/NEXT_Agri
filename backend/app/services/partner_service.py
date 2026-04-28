import asyncio
import math
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from postgrest.exceptions import APIError as PostgrestAPIError

from app.core.supabase import get_supabase_client
from app.schemas.common import PaginationMeta


class PartnerService:
    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = get_supabase_client()
        return self._client

    @property
    def table(self):
        return self.client.table("partners")

    async def list_partners(
        self,
        *,
        user_id: UUID,
        status: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[dict], PaginationMeta]:
        # 임베디드 조인으로 partner_user 정보를 한 번에 조회 (N+1 제거)
        query = (
            self.table.select(
                "*, partner_user:users!partner_user_id(name, company_name, role, phone)",
                count="exact",
            )
            .eq("user_id", str(user_id))
            .is_("deleted_at", None)  # soft delete 된 행 제외
        )

        if status:
            query = query.eq("status", status)

        # 검색을 DB 쿼리 레벨에서 처리 (클라이언트 사이드 필터링 제거)
        # nickname 또는 거래처 이름/업체명으로 검색
        if search:
            query = query.or_(
                f"nickname.ilike.%{search}%,"
                f"partner_user.name.ilike.%{search}%,"
                f"partner_user.company_name.ilike.%{search}%"
            )

        # 페이지네이션을 DB 쿼리에서 처리
        offset = (page - 1) * limit
        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)

        result = await asyncio.to_thread(lambda: query.execute())
        total = result.count or 0

        # 조인된 partner_user 데이터를 PartnerResponse 호환 형식으로 flatten
        partners = []
        for p in result.data:
            partner_user = p.pop("partner_user", None) or {}
            p["partner_name"] = partner_user.get("name")
            p["partner_company"] = partner_user.get("company_name")
            p["partner_role"] = partner_user.get("role")
            p["partner_phone"] = partner_user.get("phone")
            partners.append(p)

        meta = PaginationMeta(
            total=total,
            page=page,
            limit=limit,
            total_pages=math.ceil(total / limit) if total > 0 else 0,
        )
        return partners, meta

    # ===========================================
    # V1.6 — 양방향 승인 모델
    # ===========================================
    @staticmethod
    def _is_unique_violation(e: Exception) -> bool:
        """PostgREST unique_violation (23505) 감지."""
        err_code = getattr(e, "code", "") or ""
        err_msg = (getattr(e, "message", "") or "") + " " + str(e)
        return (
            err_code == "23505"
            or "23505" in err_msg
            or "duplicate" in err_msg.lower()
        )

    async def create_partner(self, user_id: UUID, data: dict) -> dict:
        """V1.6 — 양방향 승인 모델.

        본인 row(PENDING_OUTGOING) + 상대 row(PENDING_INCOMING) 두 row 동시 생성.
        - 두 row 모두 partial unique index (user_id, partner_user_id) WHERE deleted_at IS NULL
          제약을 받는다 → 중복 요청은 23505 로 차단.
        - 본인 row INSERT 성공 + 상대 row INSERT 실패 시 → 본인 row hard-delete 보상.
          (이후 사용자는 다시 요청 가능 — partial unique index 도 영향 없음)
        - 응답: 본인 row(PENDING_OUTGOING) 만 partner_user 임베딩으로 반환.

        notes/nickname 은 본인 row 에만 적용 — 상대 row 는 빈 값.
        """
        user_id_str = str(user_id)
        partner_user_id_str = str(data["partner_user_id"])

        # 자기 자신을 거래처로 등록 차단
        if user_id_str == partner_user_id_str:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="자기 자신을 거래처로 등록할 수 없습니다.",
            )

        outgoing_payload = {
            "user_id": user_id_str,
            "partner_user_id": partner_user_id_str,
            "status": "PENDING_OUTGOING",
            "nickname": data.get("nickname"),
            "notes": data.get("notes"),
        }
        incoming_payload = {
            "user_id": partner_user_id_str,
            "partner_user_id": user_id_str,
            "status": "PENDING_INCOMING",
        }

        # 1) 본인 row (PENDING_OUTGOING) INSERT
        try:
            outgoing_result = await asyncio.to_thread(
                lambda: self.table.insert(outgoing_payload).execute()
            )
        except PostgrestAPIError as e:
            if self._is_unique_violation(e):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="이미 등록되었거나 요청 중인 거래처입니다.",
                ) from e
            raise

        if not outgoing_result.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="거래처 등록에 실패했습니다.",
            )
        outgoing_row = outgoing_result.data[0]
        outgoing_id = outgoing_row["id"]

        # 2) 상대 row (PENDING_INCOMING) INSERT — 실패 시 본인 row hard-delete 보상
        try:
            incoming_result = await asyncio.to_thread(
                lambda: self.table.insert(incoming_payload).execute()
            )
            if not incoming_result.data:
                raise RuntimeError("상대 row INSERT 결과가 비어있습니다.")
        except Exception as e:
            # 보상 — 본인 row hard-delete
            try:
                await asyncio.to_thread(
                    lambda: self.table.delete().eq("id", outgoing_id).execute()
                )
            except Exception as rollback_err:
                print(
                    f"[partner_service.create_partner] rollback 실패 "
                    f"outgoing_id={outgoing_id}: {type(rollback_err).__name__}: {rollback_err}"
                )

            if isinstance(e, PostgrestAPIError) and self._is_unique_violation(e):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="상대방과 이미 거래처 관계가 존재합니다.",
                ) from e
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"거래처 요청 생성에 실패했습니다: {type(e).__name__}: {e}",
            ) from e

        # 3) 응답 — 본인 row 에 partner_user 임베딩
        result = await asyncio.to_thread(
            lambda: self.table.select(
                "*, partner_user:users!partner_user_id(name, company_name, role, phone)"
            )
            .eq("id", outgoing_id)
            .single()
            .execute()
        )
        row = result.data or outgoing_row
        partner_user = row.pop("partner_user", None) or {}
        row["partner_name"] = partner_user.get("name")
        row["partner_company"] = partner_user.get("company_name")
        row["partner_role"] = partner_user.get("role")
        row["partner_phone"] = partner_user.get("phone")
        return row

    async def _find_counterpart_row(
        self, *, my_user_id: str, partner_user_id: str
    ) -> Optional[dict]:
        """반대편 row 조회.

        본인 row 가 (user_id=A, partner_user_id=B) 이면
        반대편 row 는 (user_id=B, partner_user_id=A).
        """
        result = await asyncio.to_thread(
            lambda: self.table.select("*")
            .eq("user_id", partner_user_id)
            .eq("partner_user_id", my_user_id)
            .is_("deleted_at", None)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    async def accept_partner(self, partner_id: UUID, user_id: UUID) -> dict:
        """받은 거래처 요청 수락.

        조건:
          - partner_id 의 row 가 user_id 의 것이고 status='PENDING_INCOMING'
        동작:
          - 본인 row + 반대편 row 모두 status='ACTIVE' 로 UPDATE
          - 본인 row(에 partner_user 임베딩) 반환
        """
        user_id_str = str(user_id)

        # 1) 본인 row 조회 + 검증
        my_result = await asyncio.to_thread(
            lambda: self.table.select("*")
            .eq("id", str(partner_id))
            .eq("user_id", user_id_str)
            .is_("deleted_at", None)
            .single()
            .execute()
        )
        my_row = my_result.data
        if not my_row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Partner not found",
            )
        if my_row.get("status") != "PENDING_INCOMING":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"수락할 수 없는 상태입니다 (current: {my_row.get('status')})",
            )

        partner_user_id_str = str(my_row["partner_user_id"])

        # 2) 반대편 row 조회 (PENDING_OUTGOING 일 것으로 기대)
        counterpart = await self._find_counterpart_row(
            my_user_id=user_id_str,
            partner_user_id=partner_user_id_str,
        )

        # 3) 본인 row UPDATE → ACTIVE
        await asyncio.to_thread(
            lambda: self.table.update({"status": "ACTIVE"})
            .eq("id", str(partner_id))
            .is_("deleted_at", None)
            .execute()
        )

        # 4) 반대편 row UPDATE → ACTIVE (있다면)
        if counterpart:
            try:
                await asyncio.to_thread(
                    lambda: self.table.update({"status": "ACTIVE"})
                    .eq("id", counterpart["id"])
                    .is_("deleted_at", None)
                    .execute()
                )
            except Exception as e:
                # 반대편 UPDATE 실패는 치명적이지 않음 — 로그만 남기고 본인 row 는 ACTIVE 유지
                print(
                    f"[partner_service.accept_partner] 반대편 UPDATE 실패 "
                    f"counterpart_id={counterpart['id']}: {type(e).__name__}: {e}"
                )
        else:
            # 반대편 row 가 없는 비정상 상태 — 로그만
            print(
                f"[partner_service.accept_partner] 반대편 row 없음 "
                f"my_user={user_id_str} partner_user={partner_user_id_str}"
            )

        # 5) 응답 — partner_user 임베딩 포함
        final_result = await asyncio.to_thread(
            lambda: self.table.select(
                "*, partner_user:users!partner_user_id(name, company_name, role, phone)"
            )
            .eq("id", str(partner_id))
            .single()
            .execute()
        )
        row = final_result.data
        if row:
            partner_user = row.pop("partner_user", None) or {}
            row["partner_name"] = partner_user.get("name")
            row["partner_company"] = partner_user.get("company_name")
            row["partner_role"] = partner_user.get("role")
            row["partner_phone"] = partner_user.get("phone")
        return row or my_row

    async def reject_partner(self, partner_id: UUID, user_id: UUID) -> bool:
        """받은 거래처 요청 거절.

        조건:
          - partner_id 의 row 가 user_id 의 것이고 status='PENDING_INCOMING'
        동작:
          - 본인 row + 반대편 row 모두 soft-delete (deleted_at = NOW)
        """
        user_id_str = str(user_id)
        deleted_at = datetime.now(timezone.utc).isoformat()

        # 1) 본인 row 조회 + 검증
        my_result = await asyncio.to_thread(
            lambda: self.table.select("*")
            .eq("id", str(partner_id))
            .eq("user_id", user_id_str)
            .is_("deleted_at", None)
            .single()
            .execute()
        )
        my_row = my_result.data
        if not my_row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Partner not found",
            )
        if my_row.get("status") != "PENDING_INCOMING":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"거절할 수 없는 상태입니다 (current: {my_row.get('status')})",
            )

        partner_user_id_str = str(my_row["partner_user_id"])

        # 2) 반대편 row 조회
        counterpart = await self._find_counterpart_row(
            my_user_id=user_id_str,
            partner_user_id=partner_user_id_str,
        )

        # 3) 본인 row soft-delete
        await asyncio.to_thread(
            lambda: self.table.update({"deleted_at": deleted_at})
            .eq("id", str(partner_id))
            .is_("deleted_at", None)
            .execute()
        )

        # 4) 반대편 row soft-delete
        if counterpart:
            try:
                await asyncio.to_thread(
                    lambda: self.table.update({"deleted_at": deleted_at})
                    .eq("id", counterpart["id"])
                    .is_("deleted_at", None)
                    .execute()
                )
            except Exception as e:
                print(
                    f"[partner_service.reject_partner] 반대편 soft-delete 실패 "
                    f"counterpart_id={counterpart['id']}: {type(e).__name__}: {e}"
                )

        return True

    async def update_partner(
        self, partner_id: UUID, user_id: UUID, data: dict
    ) -> Optional[dict]:
        update_data = {k: v for k, v in data.items() if v is not None}
        if not update_data:
            return None

        result = await asyncio.to_thread(
            lambda: self.table.update(update_data)
            .eq("id", str(partner_id))
            .eq("user_id", str(user_id))
            .is_("deleted_at", None)  # 이미 삭제된 행은 수정 차단
            .execute()
        )
        return result.data[0] if result.data else None

    async def delete_partner(self, partner_id: UUID, user_id: UUID) -> bool:
        """soft delete — deleted_at 컬럼에 현재 UTC 시각을 기록한다.

        다른 서비스(product, order, calendar)와 동일한 패턴.
        이미 삭제된 행은 .is_("deleted_at", None) 조건에서 제외되어 False 반환.
        시그니처는 기존과 동일 (partner_id: UUID, user_id: UUID) → bool.
        """
        deleted_at = datetime.now(timezone.utc).isoformat()
        result = await asyncio.to_thread(
            lambda: self.table.update({"deleted_at": deleted_at})
            .eq("id", str(partner_id))
            .eq("user_id", str(user_id))
            .is_("deleted_at", None)
            .execute()
        )
        return bool(result.data)

    # ===========================================
    # 거래처 통계 (V1.5 Phase 1)
    # ===========================================
    async def get_stats(self, partner_id: UUID, user_id: UUID) -> dict:
        """이 거래처와의 거래 통계.

        - total_orders:         (user_id, partner_user_id) 또는 그 역의 주문 수
                                (CANCELLED 제외, soft-deleted 제외)
        - total_amount:         같은 조건 주문 합계 금액
        - last_order_date:      가장 최근 주문 created_at (date)
        - active_subscriptions: ACTIVE 상태 정기배송 개수

        404: partner row 가 없거나 user_id 의 거래처가 아니면.
        """
        # 1) partners row → partner_user_id 확인
        partner_result = await asyncio.to_thread(
            lambda: self.table.select("id, user_id, partner_user_id")
            .eq("id", str(partner_id))
            .eq("user_id", str(user_id))
            .is_("deleted_at", None)
            .execute()
        )
        rows = partner_result.data or []
        if not rows:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Partner not found",
            )
        partner_user_id_str = str(rows[0]["partner_user_id"])
        user_id_str = str(user_id)

        # 2) orders 조회 — (buyer, seller) 조합 양방향
        # supabase-py 의 .or_() 는 PostgREST or 문법.
        # and(...) 으로 그룹핑.
        orders_result = await asyncio.to_thread(
            lambda: self.client.table("orders")
            .select("id, total_amount, status, created_at, buyer_id, seller_id")
            .is_("deleted_at", None)
            .neq("status", "CANCELLED")
            .or_(
                f"and(buyer_id.eq.{user_id_str},seller_id.eq.{partner_user_id_str}),"
                f"and(seller_id.eq.{user_id_str},buyer_id.eq.{partner_user_id_str})"
            )
            .order("created_at", desc=True)
            .execute()
        )
        orders = orders_result.data or []

        total_orders = len(orders)
        total_amount = sum(int(o.get("total_amount") or 0) for o in orders)
        last_order_date = None
        if orders:
            created_at_value = orders[0].get("created_at")
            if isinstance(created_at_value, str):
                # ISO 문자열 첫 10자 (YYYY-MM-DD) 추출
                last_order_date = created_at_value[:10]
            elif hasattr(created_at_value, "isoformat"):
                last_order_date = created_at_value.isoformat()[:10]

        # 3) subscriptions ACTIVE 카운트
        # subscriptions 테이블이 마이그레이션 적용 전이거나 RLS 등으로 실패해도
        # 통계 자체는 막지 않도록 try/except.
        active_subscriptions = 0
        try:
            sub_result = await asyncio.to_thread(
                lambda: self.client.table("subscriptions")
                .select("id", count="exact")
                .is_("deleted_at", None)
                .eq("status", "ACTIVE")
                .or_(
                    f"and(buyer_id.eq.{user_id_str},seller_id.eq.{partner_user_id_str}),"
                    f"and(seller_id.eq.{user_id_str},buyer_id.eq.{partner_user_id_str})"
                )
                .execute()
            )
            active_subscriptions = sub_result.count or 0
        except Exception as e:
            print(
                f"[partner_service.get_stats] subscriptions 카운트 실패 (0 처리): "
                f"{type(e).__name__}: {e}"
            )

        return {
            "total_orders": total_orders,
            "total_amount": total_amount,
            "last_order_date": last_order_date,
            "active_subscriptions": active_subscriptions,
        }


partner_service = PartnerService()
