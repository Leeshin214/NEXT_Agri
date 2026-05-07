"""알림(notifications) 서비스.

가격 협상 / 납품일 변경 / 주문 상태 변경 / 신규 채팅 메시지 4종 알림을 emit/조회/읽음 처리.
INSERT 는 service_role 만(RLS), SELECT/UPDATE 는 본인만(RLS).

- emit: order_service.* / chat_service.send_message 직후 호출 — 실패해도 다른 흐름 막지 않음.
- list_recent: 종 아이콘 패널용 최근 N건 + 미읽음 수.
- get_unread_count: 가벼운 폴링용 카운트 단일.
- mark_read / mark_all_read: 본인 알림만 is_read=true + read_at=NOW().
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from app.core.supabase import get_supabase_client
from app.schemas.notification import NotificationListMeta


logger = logging.getLogger(__name__)


# 허용 알림 타입 (DB CHECK 제약과 1:1 동기화)
ALLOWED_NOTIFICATION_TYPES = {
    "NEW_MESSAGE",
    "COUNTER_OFFER",
    "OFFER_ACCEPTED",
    "OFFER_REJECTED",
    "DELIVERY_DATE_CHANGE",
    "DELIVERY_DATE_ACCEPTED",
    "DELIVERY_DATE_REJECTED",
    "ORDER_STATUS",
    "ORDER_CANCELLED",
}


class NotificationService:
    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = get_supabase_client()
        return self._client

    @property
    def table(self):
        return self.client.table("notifications")

    # ===========================================
    # emit — 알림 INSERT (서버 내부에서만 호출)
    # ===========================================
    async def emit(
        self,
        user_id: UUID | str,
        notification_type: str,
        title: str,
        body: str,
        link_url: Optional[str] = None,
        order_id: Optional[UUID | str] = None,
        room_id: Optional[UUID | str] = None,
    ) -> None:
        """notifications 테이블에 알림 INSERT.

        실패해도 예외 던지지 않고 logger.error 만 — 호출처(주문/채팅 흐름) 보호.
        notification_type 이 화이트리스트에 없으면 logger.error 후 skip.
        """
        if notification_type not in ALLOWED_NOTIFICATION_TYPES:
            logger.error(
                "[notification_service.emit] 알 수 없는 type=%r → skip",
                notification_type,
            )
            return

        # 본문 길이 가드 (DB 컬럼 자체는 TEXT 무제한이지만 실제 표기/모바일 푸시 대비)
        # title 200, body 500자에서 truncate.
        truncated_title = title if len(title) <= 200 else title[:197] + "..."
        truncated_body = body if len(body) <= 500 else body[:497] + "..."

        payload: dict = {
            "user_id": str(user_id),
            "type": notification_type,
            "title": truncated_title,
            "body": truncated_body,
        }
        if link_url:
            payload["link_url"] = link_url
        if order_id is not None:
            payload["order_id"] = str(order_id)
        if room_id is not None:
            payload["room_id"] = str(room_id)

        try:
            await asyncio.to_thread(
                lambda: self.table.insert(payload).execute()
            )
        except Exception as e:
            # 다른 흐름 막지 않음 — 로그만
            logger.error(
                "[notification_service.emit] INSERT 실패 (무시): "
                "user_id=%s type=%s error=%s: %s",
                user_id,
                notification_type,
                type(e).__name__,
                e,
            )

    # ===========================================
    # list_recent — 종 아이콘 패널 최근 알림 + 미읽음 수
    # ===========================================
    async def list_recent(
        self,
        user_id: UUID | str,
        *,
        limit: int = 30,
        only_unread: bool = False,
    ) -> tuple[list[dict], NotificationListMeta]:
        """본인 알림 최근 N건 + 미읽음 수 + 전체 수.

        - only_unread=True 면 미읽음만 반환 (전체 수는 미읽음 수와 동일하게 처리).
        - 정렬은 created_at DESC.
        """
        user_id_str = str(user_id)

        # 1) 최근 알림 목록
        list_query = (
            self.table.select("*", count="exact")
            .eq("user_id", user_id_str)
            .order("created_at", desc=True)
            .limit(limit)
        )
        if only_unread:
            list_query = list_query.eq("is_read", False)

        list_result = await asyncio.to_thread(lambda: list_query.execute())
        rows = list_result.data or []
        total = list_result.count or 0

        # 2) 미읽음 수 (only_unread 면 total 과 동일)
        if only_unread:
            unread_count = total
        else:
            unread_result = await asyncio.to_thread(
                lambda: self.table.select("id", count="exact")
                .eq("user_id", user_id_str)
                .eq("is_read", False)
                .execute()
            )
            unread_count = unread_result.count or 0

        meta = NotificationListMeta(unread_count=unread_count, total=total)
        return rows, meta

    # ===========================================
    # mark_read — 단건 읽음 처리
    # ===========================================
    async def mark_read(
        self, user_id: UUID | str, notification_id: UUID | str
    ) -> dict:
        """본인 알림 1건만 is_read=true + read_at=NOW() 처리.

        반환: 업데이트된 row (없으면 빈 dict — 권한 없음 또는 존재하지 않음).

        구현 메모(2026-04-29 버그 수정):
          supabase-py 2.x 의 `update().execute()` 는 representation 응답이
          비어있는 경우(헤더 누락 / RLS 의 SELECT-after-UPDATE 차단 / 서버측 정책 등)
          UPDATE 가 성공했더라도 `result.data == []` 로 돌아올 수 있다.
          이 때문에 라우터가 잘못된 404 를 던지고, 프론트의 optimistic update
          가 롤백되어 "안 읽음" 점이 사라지지 않는 버그가 있었다.
          → 본인 row 존재를 먼저 select 로 확인하고, UPDATE 후 다시 select
            해서 최신 상태를 명시적으로 반환한다 (representation 응답 의존 제거).
        """
        read_at = datetime.now(timezone.utc).isoformat()
        user_id_str = str(user_id)
        nid_str = str(notification_id)

        # 1) 본인 row 존재 확인 — 없으면 빈 dict 반환 (라우터가 404 처리)
        pre = await asyncio.to_thread(
            lambda: self.table.select("id")
            .eq("id", nid_str)
            .eq("user_id", user_id_str)
            .limit(1)
            .execute()
        )
        if not (pre.data or []):
            return {}

        # 2) UPDATE — 결과 representation 은 신뢰하지 않고 무시
        await asyncio.to_thread(
            lambda: self.table.update({"is_read": True, "read_at": read_at})
            .eq("id", nid_str)
            .eq("user_id", user_id_str)
            .execute()
        )

        # 3) 최신 row 재조회 (representation 보장 — supabase-py 헤더와 무관)
        after = await asyncio.to_thread(
            lambda: self.table.select("*")
            .eq("id", nid_str)
            .eq("user_id", user_id_str)
            .limit(1)
            .execute()
        )
        rows = after.data or []
        return rows[0] if rows else {}

    # ===========================================
    # mark_all_read — 전체 읽음 처리
    # ===========================================
    async def mark_all_read(self, user_id: UUID | str) -> int:
        """본인의 모든 미읽음 알림을 is_read=true + read_at=NOW().

        반환: 읽음 처리된 행 수.

        구현 메모(2026-04-29 버그 수정):
          mark_read 와 동일한 사유 — `update().execute()` 의 representation
          응답이 빈 배열로 오면 `len(result.data) == 0` 이 되어
          프론트가 "0건 처리됨" 으로 인식하고 갱신 후에도 안 읽음 표시가 남았다.
          → UPDATE 전에 미읽음 수를 사전 카운트하고, UPDATE 실행 후
            그 카운트를 그대로 반환해 representation 응답에 의존하지 않는다.
        """
        read_at = datetime.now(timezone.utc).isoformat()
        user_id_str = str(user_id)

        # 1) 미읽음 수 사전 카운트 (head 패턴 — 본문 거의 안 받음)
        pre = await asyncio.to_thread(
            lambda: self.table.select("id", count="exact")
            .eq("user_id", user_id_str)
            .eq("is_read", False)
            .execute()
        )
        pending = pre.count or 0
        if pending == 0:
            return 0

        # 2) UPDATE — 결과 representation 은 신뢰하지 않음
        await asyncio.to_thread(
            lambda: self.table.update({"is_read": True, "read_at": read_at})
            .eq("user_id", user_id_str)
            .eq("is_read", False)
            .execute()
        )

        return pending

    # ===========================================
    # get_unread_count — 가벼운 폴링용
    # ===========================================
    async def get_unread_count(self, user_id: UUID | str) -> int:
        """본인 미읽음 알림 수만 반환 (count head 패턴)."""
        result = await asyncio.to_thread(
            lambda: self.table.select("id", count="exact")
            .eq("user_id", str(user_id))
            .eq("is_read", False)
            .execute()
        )
        return result.count or 0


notification_service = NotificationService()
