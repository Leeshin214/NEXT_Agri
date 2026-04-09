import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.security import verify_supabase_jwt
from app.core.supabase import get_supabase_client
from app.services.chat_service import chat_service
from app.websocket.connection_manager import manager

router = APIRouter()


async def _get_user_from_token(token: str) -> dict | None:
    """JWT 토큰을 검증하고 users 테이블에서 사용자를 조회한다."""
    try:
        payload = await verify_supabase_jwt(token)
        supabase_uid = payload.get("sub")
        if not supabase_uid:
            print(f"[WS AUTH] sub 없음 in payload")
            return None

        client = get_supabase_client()
        result = await asyncio.to_thread(
            lambda: client.table("users")
            .select("*")
            .eq("supabase_uid", supabase_uid)
            .single()
            .execute()
        )
        if not result.data:
            print(f"[WS AUTH] 사용자 없음: supabase_uid={supabase_uid}")
        return result.data or None
    except Exception as e:
        print(f"[WS AUTH] 인증 실패: {type(e).__name__}: {e}")
        return None


async def _get_room(room_id: str) -> dict | None:
    """채팅방 조회"""
    try:
        client = get_supabase_client()
        result = await asyncio.to_thread(
            lambda: client.table("chat_rooms")
            .select("*")
            .eq("id", room_id)
            .single()
            .execute()
        )
        if not result.data:
            print(f"[WS ROOM] 채팅방 없음: room_id={room_id}")
        return result.data or None
    except Exception as e:
        print(f"[WS ROOM] 조회 실패: {type(e).__name__}: {e}")
        return None


@router.websocket("/ws/chat/{room_id}")
async def websocket_chat(websocket: WebSocket, room_id: str):
    """
    WebSocket 채팅 엔드포인트
    URL: /ws/chat/{room_id}?token={jwt_token}

    수신 형식: {"type": "message", "content": "내용"}
    송신 형식: {"type": "message", "id": "...", "room_id": "...",
               "sender_id": "...", "content": "...",
               "is_read": false, "created_at": "ISO8601"}
    오류 형식: {"type": "error", "message": "에러메시지"}
    """
    # 1. query param에서 token 추출
    token = websocket.query_params.get("token")
    if not token:
        print(f"[WS] 토큰 없음 → close(4001)")
        await websocket.close(code=4001)
        return

    # 2. JWT 검증 및 사용자 조회
    user = await _get_user_from_token(token)
    if not user:
        print(f"[WS] 사용자 인증 실패 → close(4001)")
        await websocket.close(code=4001)
        return

    # 3. 채팅방 존재 여부 + 참여자 확인
    room = await _get_room(room_id)
    if not room:
        print(f"[WS] 채팅방 없음: room_id={room_id} → close(4004)")
        await websocket.close(code=4004)
        return

    user_id = str(user["id"])
    if user_id not in (str(room["seller_id"]), str(room["buyer_id"])):
        print(f"[WS] 참여자 아님: user_id={user_id}, seller={room['seller_id']}, buyer={room['buyer_id']} → close(4003)")
        await websocket.close(code=4003)
        return

    # 4. 연결 수락
    print(f"[WS] 연결 수락: user_id={user_id}, room_id={room_id}")
    await manager.connect(room_id, websocket)

    try:
        # 5. 메시지 수신 루프
        while True:
            data = await websocket.receive_json()

            if data.get("type") != "message":
                await websocket.send_json(
                    {"type": "error", "message": "지원하지 않는 메시지 유형입니다."}
                )
                continue

            content = data.get("content", "").strip()
            if not content:
                await websocket.send_json(
                    {"type": "error", "message": "메시지 내용이 비어있습니다."}
                )
                continue

            # 6. DB 저장
            from uuid import UUID

            message = await chat_service.send_message(
                room_id=UUID(room_id),
                sender_id=UUID(user_id),
                content=content,
            )

            # 7. 방의 모든 연결에 브로드캐스트
            broadcast_payload = {
                "type": "message",
                "id": str(message["id"]),
                "room_id": str(message["room_id"]),
                "sender_id": str(message["sender_id"]),
                "content": message["content"],
                "is_read": message["is_read"],
                "created_at": message["created_at"],
            }
            await manager.broadcast(room_id, broadcast_payload)

    except WebSocketDisconnect:
        # 8. 연결 끊김 처리
        manager.disconnect(room_id, websocket)
    except Exception as e:
        # 예상치 못한 오류 — 연결 정리 후 종료
        manager.disconnect(room_id, websocket)
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
