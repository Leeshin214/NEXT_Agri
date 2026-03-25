# SKILL_CHAT.md — Realtime Chat Agent

## 역할
판매자-구매자 간 실시간 채팅을 구현한다.  
Supabase Realtime을 1차로 사용하고, 복잡한 요구사항이 생기면 FastAPI WebSocket으로 전환한다.

---

## 아키텍처: WebSocket (송신) + Supabase Realtime (수신 fallback)

**현재 구현 방식 (검증됨)**:
- 메시지 **전송**: WebSocket (`useWebSocketChat` → `sendMessage`)
- 메시지 **수신**: WebSocket `lastMessage` → React Query 캐시 즉시 반영
- 초기 메시지 **로드**: REST API (`GET /chat/rooms/{room_id}/messages`)
- 채팅방 목록 갱신: Supabase Realtime (`chat_rooms` UPDATE/INSERT)

```
[메시지 전송 플로우 — WebSocket]
1. 사용자가 메시지 입력 후 전송
2. useWebSocketChat.sendMessage() → WS send {"type":"message","content":"..."}
3. 서버 → WS broadcast {"type":"message", id, room_id, sender_id, content, ...}
4. useMessagesWithWebSocket의 useEffect → React Query 캐시 즉시 업데이트
5. 메시지 목록 UI 즉시 반영

[초기 로드 플로우]
1. 채팅방 선택
2. REST GET /chat/rooms/{room_id}/messages → React Query 캐시 저장
3. 이후 WS 수신 메시지가 캐시에 append됨
```

---

## 채팅방 생성 로직

```
- 주문/견적이 생성될 때 자동으로 채팅방 생성 (FastAPI 서비스에서 처리)
- 또는 "채팅 시작" 버튼 클릭 시 채팅방 생성 (없으면 신규 생성, 있으면 기존 사용)
```

---

## Backend 구현

### FastAPI Chat 라우터
```python
# app/api/v1/chat.py
from fastapi import APIRouter, Depends, HTTPException
from app.dependencies import get_current_user, get_db

router = APIRouter(prefix="/chat", tags=["chat"])

@router.get("/rooms")
async def get_chat_rooms(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """현재 사용자의 채팅방 목록 조회"""
    query = select(ChatRoom).where(
        (ChatRoom.seller_id == current_user.id) |
        (ChatRoom.buyer_id == current_user.id)
    ).order_by(ChatRoom.last_message_at.desc().nullslast())
    
    rooms = await db.execute(query)
    return {"data": rooms.scalars().all()}

@router.get("/rooms/{room_id}/messages")
async def get_messages(
    room_id: UUID,
    page: int = 1,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """채팅방 메시지 목록 (최신순 → 뒤집어서 표시)"""
    # 채팅방 접근 권한 확인
    room = await db.get(ChatRoom, room_id)
    if not room or (room.seller_id != current_user.id and room.buyer_id != current_user.id):
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다")
    
    offset = (page - 1) * limit
    query = (
        select(Message)
        .where(Message.room_id == room_id)
        .order_by(Message.created_at.desc())
        .offset(offset).limit(limit)
    )
    messages = await db.execute(query)
    return {"data": list(reversed(messages.scalars().all()))}

@router.post("/rooms/{room_id}/messages")
async def send_message(
    room_id: UUID,
    body: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """메시지 전송"""
    message = Message(
        room_id=room_id,
        sender_id=current_user.id,
        content=body.content
    )
    db.add(message)
    
    # 채팅방 마지막 메시지 업데이트
    await db.execute(
        update(ChatRoom)
        .where(ChatRoom.id == room_id)
        .values(last_message=body.content, last_message_at=func.now())
    )
    
    await db.commit()
    await db.refresh(message)
    return {"data": message}

@router.post("/rooms/{room_id}/read")
async def mark_as_read(
    room_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """메시지 읽음 처리"""
    await db.execute(
        update(Message)
        .where(
            Message.room_id == room_id,
            Message.sender_id != current_user.id,
            Message.is_read == False
        )
        .values(is_read=True)
    )
    await db.commit()
    return {"data": {"success": True}}
```

---

## Frontend 구현

### useWebSocketChat 훅 (신규 — 검증됨)
```typescript
// frontend/hooks/useWebSocketChat.ts
// WS URL: process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000'
// 연결: ws://…/ws/chat/{roomId}?token={jwt}
// roomId null → 연결 안 함
// 재연결: 3초 후 최대 3회
// 반환값: { isConnected, sendMessage, lastMessage, error }

import { useWebSocketChat } from '@/hooks/useWebSocketChat';
const { isConnected, sendMessage, lastMessage, error } = useWebSocketChat(roomId);
// sendMessage(content) → WS send {"type":"message","content":"..."}
// lastMessage: WebSocketMessage | null — 수신 시마다 갱신
```

### useMessagesWithWebSocket 훅 (신규 — 검증됨)
```typescript
// frontend/hooks/useChat.ts — 채팅 페이지에서 사용하는 통합 훅
import { useMessagesWithWebSocket } from '@/hooks/useChat';

const { messageQuery, isConnected, sendMessage, wsError } =
  useMessagesWithWebSocket(roomId); // roomId: string | null

// messageQuery.data?.data → Message[] (초기 REST 로드 + WS 수신 메시지 포함)
// sendMessage(content) → WS 전송
// isConnected → 헤더 연결 상태 인디케이터에 사용
// wsError → 헤더 아래 에러 텍스트 표시
```

### 채팅 페이지 패턴 (seller/buyer 공통 — 검증됨)
```tsx
// useSendMessage (REST mutation) 대신 useMessagesWithWebSocket 사용
// 전송 버튼 disabled: !message.trim() || !isConnected
// 헤더 연결 인디케이터: isConnected ? 'bg-green-500' : 'bg-gray-300'

const { messageQuery, isConnected, sendMessage: wsSendMessage, wsError } =
  useMessagesWithWebSocket(selectedRoomId);
const messages = messageQuery.data?.data ?? [];

const handleSend = () => {
  if (!message.trim() || !selectedRoomId) return;
  wsSendMessage(message);
  setMessage('');
};
```

### useChat.ts 현재 export 목록
- `useChatRooms` — 채팅방 목록 + Supabase Realtime 구독
- `useMessages` — 메시지 목록 + Supabase Realtime 구독 (레거시, 직접 사용 안 함)
- `useMessagesWithWebSocket` — 초기 로드(REST) + WS 실시간 송수신 통합 (채팅 페이지용)
- `useSendMessage` — REST 전송 mutation (레거시, 직접 사용 안 함)
- `useCreateChatRoom`, `useMarkAsRead`, `useSummarizeChat`

---

## AI 채팅 요약 기능

```typescript
// AI 요약 버튼 클릭 시
const summarizeChat = async () => {
  const recentMessages = messages.slice(-20)
    .map(m => `${m.sender?.name}: ${m.content}`)
    .join('\n');
  
  const response = await api.post('/ai/summarize-chat', {
    messages: recentMessages,
    context: '농산물 유통 거래 채팅'
  });
  
  setSummary(response.data.summary);
};
```

---

## Supabase Realtime 활성화 설정

```sql
-- messages 테이블 realtime 활성화
ALTER PUBLICATION supabase_realtime ADD TABLE messages;
ALTER PUBLICATION supabase_realtime ADD TABLE chat_rooms;
```

---

## 환경변수

```
NEXT_PUBLIC_WS_URL=ws://localhost:8000   # 미설정 시 이 값이 기본값으로 사용됨
# 프로덕션: wss://your-backend.railway.app
```

## 주의사항 & 함정

- `useWebSocketChat`의 `connect` 함수는 `roomIdRef`를 사용하므로 deps 배열이 비어있다. roomId 변경은 useEffect에서 `retryCountRef.current = 0` 후 `connect()` 재호출로 처리.
- WS 언마운트 시 `ws.onclose = null` 먼저 설정 후 `ws.close()` — 그렇지 않으면 onclose가 재연결 타이머를 등록해 메모리 누수 발생.
- `useMessagesWithWebSocket`에서 WS 수신 메시지를 캐시에 추가할 때 `id` 중복 체크 필수 — 서버가 동일 메시지를 두 번 보낼 경우 대비.
- 전송 버튼 disabled를 `!isConnected`로 설정 — WS 미연결 상태에서 전송 시도 방지.

## 작업 체크리스트

- [ ] FastAPI chat 라우터 (rooms, messages CRUD)
- [ ] SQLAlchemy ChatRoom, Message 모델
- [ ] Supabase Realtime publication 설정
- [x] useWebSocketChat 훅 (WS 연결, 재연결, 송수신)
- [x] useChat 훅 (useChatRooms, useMessagesWithWebSocket 등)
- [ ] ChatRoomList 컴포넌트
- [x] seller/buyer 채팅 페이지 (WebSocket 통합, 연결 인디케이터)
- [x] 읽음 처리 (채팅방 진입 시 자동)
- [x] 안읽은 메시지 수 뱃지
- [x] AI 요약 버튼 연동
