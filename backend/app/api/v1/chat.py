from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_current_user
from app.schemas.chat import (
    ChatRoomCreate,
    ChatRoomResponse,
    MessageCreate,
    MessageResponse,
)
from app.schemas.common import SuccessResponse
from app.services.chat_service import chat_service

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
    current_user: dict = Depends(get_current_user),
):
    """메시지 전송"""
    message = await chat_service.send_message(
        room_id=room_id,
        sender_id=current_user["id"],
        content=data.content,
    )
    return {"data": message}


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
