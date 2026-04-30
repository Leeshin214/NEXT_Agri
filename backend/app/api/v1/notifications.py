"""알림(notifications) API.

엔드포인트 4개:
- GET  /notifications?limit=30&only_unread=false      목록 + meta(unread_count, total)
- GET  /notifications/unread-count                    가벼운 폴링용 카운트
- POST /notifications/{notification_id}/read          단건 읽음
- POST /notifications/read-all                        전체 읽음

INSERT 는 서버(order_service / chat_service) 내부 emit 으로만 발생 — 외부 노출 없음.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_current_user
from app.schemas.common import SuccessResponse
from app.schemas.notification import (
    MarkAllReadResponse,
    NotificationResponse,
    UnreadCountResponse,
)
from app.services.notification_service import notification_service


router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get(
    "",
    response_model=SuccessResponse[list[NotificationResponse]],
)
async def list_notifications(
    limit: int = Query(30, ge=1, le=100),
    only_unread: bool = Query(False),
    current_user: dict = Depends(get_current_user),
):
    """본인 알림 최근 N건 + meta(unread_count, total).

    - limit: 1~100 (기본 30) — 종 아이콘 패널 노출용
    - only_unread: True 면 미읽음만 (total 도 미읽음 수와 동일)
    """
    rows, meta = await notification_service.list_recent(
        user_id=current_user["id"],
        limit=limit,
        only_unread=only_unread,
    )
    return {
        "data": rows,
        "meta": meta.model_dump(),
    }


@router.get(
    "/unread-count",
    response_model=SuccessResponse[UnreadCountResponse],
)
async def get_unread_count(
    current_user: dict = Depends(get_current_user),
):
    """본인 미읽음 알림 수만 반환 (가벼운 폴링용 fallback)."""
    count = await notification_service.get_unread_count(
        user_id=current_user["id"]
    )
    return {"data": {"unread_count": count}}


@router.post(
    "/{notification_id}/read",
    response_model=SuccessResponse[NotificationResponse],
)
async def mark_notification_read(
    notification_id: UUID,
    current_user: dict = Depends(get_current_user),
):
    """단건 읽음 처리. 본인 알림이 아니면 404."""
    row = await notification_service.mark_read(
        user_id=current_user["id"],
        notification_id=notification_id,
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="알림을 찾을 수 없습니다.",
        )
    return {"data": row}


@router.post(
    "/read-all",
    response_model=SuccessResponse[MarkAllReadResponse],
)
async def mark_all_notifications_read(
    current_user: dict = Depends(get_current_user),
):
    """본인 미읽음 알림 전체 읽음 처리."""
    updated = await notification_service.mark_all_read(
        user_id=current_user["id"]
    )
    return {"data": {"updated": updated}}
