# SKILL_CHAT.md — Realtime Chat Agent

## 역할
판매자-구매자 간 실시간 채팅을 구현한다.  
Supabase Realtime을 1차로 사용하고, 복잡한 요구사항이 생기면 FastAPI WebSocket으로 전환한다.

---

## 아키텍처 선택: Supabase Realtime

Supabase의 `postgres_changes` 이벤트를 활용한다.  
메시지 INSERT 이벤트를 구독하여 실시간으로 UI에 반영한다.

```
[메시지 전송 플로우]
1. 사용자가 메시지 입력 후 전송
2. Frontend → FastAPI POST /chat/messages
3. FastAPI → Supabase DB INSERT (messages 테이블)
4. Supabase Realtime → 해당 room을 구독 중인 상대방에게 이벤트 발송
5. 상대방 Frontend → 메시지 UI에 실시간 추가
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

### Supabase Realtime 구독 훅
```typescript
// src/hooks/useChat.ts
import { useEffect, useRef, useState } from 'react';
import { createClient } from '@/lib/supabase/client';
import { api } from '@/lib/api';
import type { Message, ChatRoom } from '@/types/chat';

export function useChatMessages(roomId: string | null) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const supabase = createClient();

  // 초기 메시지 로드
  useEffect(() => {
    if (!roomId) return;
    setIsLoading(true);
    api.get(`/chat/rooms/${roomId}/messages`)
      .then((res) => setMessages(res.data))
      .finally(() => setIsLoading(false));
  }, [roomId]);

  // Realtime 구독
  useEffect(() => {
    if (!roomId) return;

    const channel = supabase
      .channel(`room:${roomId}`)
      .on(
        'postgres_changes',
        {
          event: 'INSERT',
          schema: 'public',
          table: 'messages',
          filter: `room_id=eq.${roomId}`,
        },
        (payload) => {
          setMessages((prev) => [...prev, payload.new as Message]);
        }
      )
      .subscribe();

    return () => { supabase.removeChannel(channel); };
  }, [roomId]);

  const sendMessage = async (content: string) => {
    if (!roomId || !content.trim()) return;
    await api.post(`/chat/rooms/${roomId}/messages`, { content });
    // Realtime이 처리하므로 낙관적 업데이트 필요 없음
    // 단, 자신의 메시지는 즉시 표시하고 싶으면 낙관적 업데이트 추가
  };

  return { messages, isLoading, sendMessage };
}

export function useChatRooms() {
  const [rooms, setRooms] = useState<ChatRoom[]>([]);
  const supabase = createClient();

  useEffect(() => {
    api.get('/chat/rooms').then((res) => setRooms(res.data));

    // 채팅방 목록도 실시간 갱신 (last_message 업데이트)
    const channel = supabase
      .channel('chat-rooms')
      .on(
        'postgres_changes',
        { event: 'UPDATE', schema: 'public', table: 'chat_rooms' },
        () => {
          api.get('/chat/rooms').then((res) => setRooms(res.data));
        }
      )
      .subscribe();

    return () => { supabase.removeChannel(channel); };
  }, []);

  return { rooms };
}
```

### ChatWindow 컴포넌트 핵심 로직
```tsx
// src/components/chat/ChatWindow.tsx
'use client';
import { useRef, useEffect } from 'react';
import { useChatMessages } from '@/hooks/useChat';
import { useAuthStore } from '@/store/authStore';

export default function ChatWindow({ roomId }: { roomId: string }) {
  const { user } = useAuthStore();
  const { messages, sendMessage } = useChatMessages(roomId);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [input, setInput] = useState('');

  // 새 메시지 올 때 스크롤 아래로
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = () => {
    if (!input.trim()) return;
    sendMessage(input);
    setInput('');
  };

  return (
    <div className="flex flex-col h-full">
      {/* 메시지 목록 */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex ${msg.sender_id === user?.id ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-xs px-4 py-2 rounded-2xl text-sm ${
                msg.sender_id === user?.id
                  ? 'bg-primary-600 text-white'
                  : 'bg-gray-100 text-gray-900'
              }`}
            >
              {msg.content}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
      {/* 입력창 */}
      <div className="border-t p-4 flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSend()}
          placeholder="메시지를 입력하세요..."
          className="flex-1 border rounded-lg px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
        />
        <button
          onClick={handleSend}
          className="bg-primary-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-primary-700"
        >
          전송
        </button>
      </div>
    </div>
  );
}
```

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

## 작업 체크리스트

- [ ] FastAPI chat 라우터 (rooms, messages CRUD)
- [ ] SQLAlchemy ChatRoom, Message 모델
- [ ] Supabase Realtime publication 설정
- [ ] useChat 훅 (메시지 목록 + 실시간 구독)
- [ ] useChatRooms 훅 (채팅방 목록 + 실시간)
- [ ] ChatRoomList 컴포넌트
- [ ] ChatWindow 컴포넌트 (스크롤, 전송)
- [ ] 읽음 처리 (채팅방 진입 시 자동)
- [ ] 안읽은 메시지 수 뱃지
- [ ] AI 요약 버튼 연동
