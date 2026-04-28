import asyncio
import math
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from postgrest.exceptions import APIError as PostgrestAPIError

from app.core.supabase import get_supabase_client
from app.schemas.common import PaginationMeta

# KST = UTC+9 (DST 없음)
_KST = timezone(timedelta(hours=9))


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
        include_last_trade: bool = False,
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

        # 최근 거래 정보 채우기 (PM Report #8 작업 5)
        # N+1 회피 — partners 의 모든 partner_user_id 를 모아 단일 쿼리로 양방향 orders 조회.
        # include_last_trade=False (default) 면 추가 쿼리 자체를 스킵 → last_trade_* 는
        # PartnerResponse Optional default(None) 로 응답된다. 거래처 페이지처럼 실제로
        # 컬럼을 사용하는 화면만 ?include_last_trade=true 로 명시 호출.
        if include_last_trade:
            await self._attach_last_trades(partners=partners, my_user_id=str(user_id))

        meta = PaginationMeta(
            total=total,
            page=page,
            limit=limit,
            total_pages=math.ceil(total / limit) if total > 0 else 0,
        )
        return partners, meta

    # ===========================================
    # 최근 거래 정보 (PM Report #8 작업 5)
    # ===========================================
    async def _attach_last_trades(
        self, *, partners: list[dict], my_user_id: str
    ) -> None:
        """partners 각 항목에 last_trade_date / last_trade_amount 를 채워 넣는다.

        N+1 회피 전략:
          1) partners 의 partner_user_id 들을 set 으로 모은다.
          2) 단일 supabase 쿼리로 (me ↔ counterpart) 양방향 orders 를 created_at DESC 로 조회.
             - WHERE deleted_at IS NULL AND status != 'CANCELLED'
             - WHERE (buyer_id=me AND seller_id IN counterparts)
                  OR (seller_id=me AND buyer_id IN counterparts)
          3) 메모리에서 counterpart_id 별 첫 (가장 최근) row 만 픽업.
          4) partners 리스트에 in-place 로 last_trade_* 필드를 세팅.

        PostgREST 는 DISTINCT ON 을 지원하지 않으므로 ORDER BY DESC 후 메모리 그룹핑이
        가장 단순하고 안정적. partner 1명당 평균 주문 N 건이라도 단일 쿼리 1회로 끝남.

        - last_trade_date  : delivery_date 가 있으면 그 값, 없으면 created_at 의 KST 날짜.
        - last_trade_amount: total_amount (KRW). NULL 이면 None.
        - 거래 이력이 없는 partner 는 두 필드 모두 None 유지.
        """
        if not partners:
            return

        # 1) counterpart 후보 수집 (중복 제거)
        counterpart_ids = {
            str(p["partner_user_id"])
            for p in partners
            if p.get("partner_user_id")
        }
        if not counterpart_ids:
            return

        counterpart_list = list(counterpart_ids)
        # PostgREST in.(...) — 콤마 구분, 따옴표 불필요 (UUID 는 안전 문자만 포함)
        in_clause = f"({','.join(counterpart_list)})"

        # 2) 단일 양방향 orders 쿼리
        # or_(...) 구조 — me 는 buyer 이거나 seller, 반대편은 IN counterparts.
        try:
            orders_result = await asyncio.to_thread(
                lambda: self.client.table("orders")
                .select(
                    "id, buyer_id, seller_id, total_amount, "
                    "delivery_date, created_at, status"
                )
                .is_("deleted_at", None)
                .neq("status", "CANCELLED")
                .or_(
                    f"and(buyer_id.eq.{my_user_id},seller_id.in.{in_clause}),"
                    f"and(seller_id.eq.{my_user_id},buyer_id.in.{in_clause})"
                )
                .order("created_at", desc=True)
                .execute()
            )
        except Exception as e:
            # 거래 정보 조회 실패는 partners 응답을 막지 않음 — 로그 후 None 유지.
            print(
                f"[partner_service._attach_last_trades] orders 조회 실패: "
                f"{type(e).__name__}: {e}"
            )
            return

        orders = orders_result.data or []

        # 3) counterpart_id 별 첫 row 만 픽업 (이미 created_at DESC 로 정렬됨)
        latest_by_counterpart: dict[str, dict] = {}
        for o in orders:
            buyer_id = str(o.get("buyer_id") or "")
            seller_id = str(o.get("seller_id") or "")
            # counterpart = me 의 반대편
            counterpart = seller_id if buyer_id == my_user_id else buyer_id
            if counterpart in latest_by_counterpart:
                continue  # 이미 더 최근 row 가 들어가 있음
            latest_by_counterpart[counterpart] = o

        # 4) partners 에 in-place 세팅
        for p in partners:
            counterpart = str(p.get("partner_user_id") or "")
            order = latest_by_counterpart.get(counterpart)
            if not order:
                p["last_trade_date"] = None
                p["last_trade_amount"] = None
                continue

            # last_trade_date — delivery_date 우선, 없으면 created_at 의 KST 날짜
            trade_date_str: Optional[str] = None
            delivery_date = order.get("delivery_date")
            if delivery_date:
                # supabase 는 DATE 컬럼을 ISO 문자열 'YYYY-MM-DD' 로 반환
                if isinstance(delivery_date, str):
                    trade_date_str = delivery_date[:10]
                elif hasattr(delivery_date, "isoformat"):
                    trade_date_str = delivery_date.isoformat()[:10]
            else:
                created_at = order.get("created_at")
                trade_date_str = self._created_at_to_kst_date_str(created_at)

            p["last_trade_date"] = trade_date_str

            total_amount = order.get("total_amount")
            p["last_trade_amount"] = (
                int(total_amount) if total_amount is not None else None
            )

    @staticmethod
    def _created_at_to_kst_date_str(created_at) -> Optional[str]:
        """created_at (ISO 문자열 또는 datetime) 을 KST 기준 YYYY-MM-DD 로 변환."""
        if not created_at:
            return None
        try:
            if isinstance(created_at, str):
                # 'Z' suffix → '+00:00' (Python 3.11+ fromisoformat 호환)
                iso = created_at.replace("Z", "+00:00")
                dt = datetime.fromisoformat(iso)
            else:
                dt = created_at
            if dt.tzinfo is None:
                # naive datetime → UTC 로 가정
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(_KST).date().isoformat()
        except Exception:
            # 파싱 실패 — 첫 10자 fallback (이미 YYYY-MM-DD 면 그대로)
            return str(created_at)[:10] if created_at else None

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
        """soft delete — V1.6 양방향 동기화.

        본인 row + 반대편 row(존재 시) 모두 deleted_at 세팅.
        - 본인 row 가 없거나 이미 삭제됨 → False (router 가 404 처리)
        - 반대편 row soft-delete 실패는 best-effort (로그만 남기고 본인 결과 유지)
        - 멱등성: 이미 삭제된 row 는 .is_("deleted_at", None) 필터로 자동 스킵 → False
        시그니처는 기존과 동일 (partner_id: UUID, user_id: UUID) → bool.
        accept_partner / reject_partner 와 동일한 패턴 (_find_counterpart_row 재사용).
        """
        user_id_str = str(user_id)
        deleted_at = datetime.now(timezone.utc).isoformat()

        # 1) 본인 row 조회 (status 무관, 본인 소유 + 미삭제 검증)
        my_result = await asyncio.to_thread(
            lambda: self.table.select("id, user_id, partner_user_id, status, deleted_at")
            .eq("id", str(partner_id))
            .eq("user_id", user_id_str)
            .is_("deleted_at", None)
            .limit(1)
            .execute()
        )
        my_rows = my_result.data or []
        if not my_rows:
            # 없거나 이미 삭제됨 → router 가 404 응답
            return False

        my_row = my_rows[0]
        partner_user_id_str = str(my_row["partner_user_id"])

        # 2) 반대편 row 조회 (best-effort)
        counterpart = await self._find_counterpart_row(
            my_user_id=user_id_str,
            partner_user_id=partner_user_id_str,
        )

        # 3) 본인 row soft-delete
        my_update_result = await asyncio.to_thread(
            lambda: self.table.update({"deleted_at": deleted_at})
            .eq("id", str(partner_id))
            .eq("user_id", user_id_str)
            .is_("deleted_at", None)
            .execute()
        )

        # 4) 반대편 row soft-delete (있을 때만, best-effort)
        if counterpart and counterpart.get("id"):
            try:
                await asyncio.to_thread(
                    lambda: self.table.update({"deleted_at": deleted_at})
                    .eq("id", counterpart["id"])
                    .is_("deleted_at", None)
                    .execute()
                )
            except Exception as e:
                print(
                    f"[partner_service.delete_partner] 반대편 soft-delete 실패 "
                    f"counterpart_id={counterpart['id']}: {type(e).__name__}: {e}"
                )
        else:
            # 반대편 row 가 없는 케이스 — 마이그레이션 전 단방향 데이터 등.
            # 본인 row 만 처리하고 진행 (best-effort).
            print(
                f"[partner_service.delete_partner] 반대편 row 없음 "
                f"my_user={user_id_str} partner_user={partner_user_id_str}"
            )

        return bool(my_update_result.data)

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
