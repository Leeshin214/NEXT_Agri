import asyncio
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from app.dependencies import get_current_user
from app.schemas.chat import (
    ChatDraftRequest,
    ChatDraftResponse,
    ChatRoomCreate,
    ChatRoomResponse,
    MessageCreate,
    MessageResponse,
    NegotiationDraftDismissResponse,
)
from app.schemas.common import SuccessResponse
from app.schemas.order import CounterOfferCreate, CounterOfferResponse
from app.core.supabase import get_supabase_client
from app.services.chat_service import chat_service
from app.services.draft_service import generate_chat_draft
from app.services.negotiation_detection_service import (
    dismiss_draft_negotiation,
    process_message_for_negotiation,
)
from app.services.order_service import order_service

router = APIRouter(prefix="/chat", tags=["chat"])


@router.get("/rooms", response_model=SuccessResponse[list[ChatRoomResponse]])
async def list_rooms(
    current_user: dict = Depends(get_current_user),
):
    """내 채팅방 목록"""
    rooms = await chat_service.list_rooms(
        user_id=current_user["id"],
        role=current_user["role"],
    )
    return {"data": rooms}


@router.post("/rooms", response_model=SuccessResponse[ChatRoomResponse], status_code=201)
async def create_room(
    data: ChatRoomCreate,
    current_user: dict = Depends(get_current_user),
):
    """채팅방 생성 (또는 기존 채팅방 반환)"""
    room = await chat_service.get_or_create_room(
        user_id=current_user["id"],
        role=current_user["role"],
        partner_user_id=data.partner_user_id,
        order_id=data.order_id,
    )
    return {"data": room}


@router.get(
    "/rooms/{room_id}/messages",
    response_model=SuccessResponse[list[MessageResponse]],
)
async def list_messages(
    room_id: UUID,
    limit: int = 50,
    before: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """채팅방 메시지 목록"""
    messages = await chat_service.list_messages(
        room_id=room_id, limit=limit, before=before
    )
    return {"data": messages}


@router.post(
    "/rooms/{room_id}/messages",
    response_model=SuccessResponse[MessageResponse],
    status_code=201,
)
async def send_message(
    room_id: UUID,
    data: MessageCreate,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    """메시지 전송 + 협상 의도 감지 백그라운드 실행 (US-2, 2026-05-04).

    응답 자체는 메시지 INSERT 결과만 즉시 반환하고,
    협상 의도 감지는 BackgroundTasks 로 비동기 실행되어 응답 시간에 영향 주지 않는다.
    감지 결과는 messages.metadata['draft_negotiation'] 에 저장되고
    발신자 본인에게만 WS `negotiation_draft_detected` 이벤트로 푸시된다.
    """
    message = await chat_service.send_message(
        room_id=room_id,
        sender_id=current_user["id"],
        content=data.content,
    )

    # 협상 의도 감지 — 비동기 (실패는 서비스 내부에서 흡수)
    background_tasks.add_task(
        process_message_for_negotiation,
        message_id=message["id"],
        room_id=room_id,
        sender_id=current_user["id"],
        content=data.content,
    )

    return {"data": message}


@router.patch(
    "/messages/{message_id}/dismiss-draft-negotiation",
    response_model=SuccessResponse[NegotiationDraftDismissResponse],
)
async def dismiss_message_draft_negotiation(
    message_id: UUID,
    current_user: dict = Depends(get_current_user),
):
    """발신자 본인이 협상 초안 카드 [무시] 클릭 시 호출.

    metadata.draft_negotiation.dismissed_at 을 NOW() 로 채운다 (멱등).

    가드 (서비스 레이어):
      - 메시지 존재 검증 → 없으면 404
      - sender_id == current_user.id 검증 → 다르면 403
      - draft_negotiation 자체 없으면 404
    """
    draft = await dismiss_draft_negotiation(
        message_id=message_id,
        user_id=current_user["id"],
    )
    return {
        "data": {
            "message_id": message_id,
            "draft_negotiation": draft,
        }
    }


@router.post("/rooms/{room_id}/read", status_code=204)
async def mark_as_read(
    room_id: UUID,
    current_user: dict = Depends(get_current_user),
):
    """메시지 읽음 처리"""
    await chat_service.mark_as_read(
        room_id=room_id,
        user_id=current_user["id"],
    )


@router.post(
    "/rooms/{room_id}/counter-offer",
    response_model=SuccessResponse[CounterOfferResponse],
    status_code=201,
)
async def submit_counter_offer_via_chat(
    room_id: UUID,
    data: CounterOfferCreate,
    current_user: dict = Depends(get_current_user),
):
    """채팅방의 현재 연결 주문에 대해 협상가 제시.

    - chat_room.order_id 가 None 이면 400 (연결된 주문 없음)
    - 호출자가 채팅방의 buyer 또는 seller 가 아니면 403
    - order_service.submit_counter_offer 를 호출 (메시지/브로드캐스트 자동)
    """
    # 1) chat_room 조회
    room_result = await asyncio.to_thread(
        lambda: chat_service.rooms.select("*")
        .eq("id", str(room_id))
        .single()
        .execute()
    )
    room = room_result.data
    if not room:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="채팅방을 찾을 수 없습니다",
        )

    # 2) 권한 검증 — buyer 또는 seller 만 허용
    user_id = str(current_user["id"])
    if user_id not in (str(room["seller_id"]), str(room["buyer_id"])):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="이 채팅방에 접근할 권한이 없습니다",
        )

    # 3) 연결된 주문 확인 — room.order_id가 취소/완료 상태면 같은 buyer-seller 간 활성 주문 자동 탐색
    order_id = room.get("order_id")
    if not order_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="이 채팅방에 연결된 주문이 없습니다",
        )

    # room.order_id 상태 확인 — 협상 불가 상태면 활성 주문으로 교체
    NEGOTIABLE_STATUSES = ("QUOTE_REQUESTED", "NEGOTIATING")
    supabase = get_supabase_client()
    order_check = await asyncio.to_thread(
        lambda: supabase.table("orders")
        .select("id, status")
        .eq("id", str(order_id))
        .is_("deleted_at", None)
        .single()
        .execute()
    )
    current_order = order_check.data
    if not current_order or current_order.get("status") not in NEGOTIABLE_STATUSES:
        # 같은 buyer-seller 간 활성 주문 탐색
        fallback = await asyncio.to_thread(
            lambda: supabase.table("orders")
            .select("id, status")
            .eq("buyer_id", str(room["buyer_id"]))
            .eq("seller_id", str(room["seller_id"]))
            .in_("status", list(NEGOTIABLE_STATUSES))
            .is_("deleted_at", None)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not fallback.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="협상 가능한 주문이 없습니다. 먼저 주문을 생성해주세요.",
            )
        order_id = fallback.data[0]["id"]

    # 4) 협상가 제시 — order_service 가 메시지/브로드캐스트 자동 처리
    offer = await order_service.submit_counter_offer(
        order_id=UUID(order_id),
        payload=data.model_dump(mode="json"),
        user=current_user,
    )
    return {"data": offer}


@router.post(
    "/draft",
    response_model=SuccessResponse[ChatDraftResponse],
)
async def create_chat_draft(
    payload: ChatDraftRequest,
    current_user: dict = Depends(get_current_user),
):
    """채팅방 컨텍스트 기반 답장 초안 생성 (US-1, 2026-05-03).

    - 입력창 `/초안 ...` 슬래시 명령에서 호출
    - 메시지 DB 저장 안 함, 초안 텍스트만 반환
    - 채팅방 참여자(seller/buyer)만 호출 가능 (draft_service 에서 검증)
    - 컨텍스트: 연결된 주문 상세, 최근 20개 메시지, 상대방 정보
    """
    draft_text = await generate_chat_draft(
        user_id=current_user["id"],
        room_id=payload.room_id,
        instruction=payload.instruction,
    )
    return {"data": {"draft": draft_text}}
