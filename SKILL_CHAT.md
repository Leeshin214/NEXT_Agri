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

// WebSocketMessage 인터페이스 (Message 타입과 필드 동기화 필수)
export interface WebSocketMessage {
  type: 'message' | 'error';
  id?: string;
  room_id?: string;
  sender_id?: string;
  content?: string;
  is_read?: boolean;
  created_at?: string;
  deleted_at?: string | null;
  message?: string; // error type일 때
}
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
- `useMessagesWithWebSocket` — 초기 로드(REST) + WS 실시간 송수신 통합 (채팅 페이지용). `negotiation_draft_detected` 이벤트도 처리
- `useSendMessage` — REST 전송 mutation (레거시, 직접 사용 안 함)
- `useCreateChatRoom`, `useMarkAsRead`, `useSummarizeChat`
- `useGenerateChatDraft` — `/초안 [지시]` 슬래시 명령용 AI 답장 초안
- `useSubmitCounterOfferViaChat(roomId)` — 채팅창에서 협상가 제시
- `useDismissNegotiationDraft(roomId)` — US-2 협상 의도 감지 카드 [무시] PATCH

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

## WebSocket 핸들러 디버그 로깅 패턴 (검증됨)

`websocket.close()`를 `websocket.accept()` 전에 호출하면 클라이언트에 403이 반환된다.
어느 단계에서 close되는지 알 수 없으므로, `_get_user_from_token` / `_get_room` / `websocket_chat` 세 곳 모두에 print 로그를 추가한다.

```python
# _get_user_from_token
except Exception as e:
    print(f"[WS AUTH] 인증 실패: {type(e).__name__}: {e}")
    return None

# _get_room
except Exception as e:
    print(f"[WS ROOM] 조회 실패: {type(e).__name__}: {e}")
    return None

# websocket_chat — 각 조기 종료 분기
print(f"[WS] 토큰 없음 → close(4001)")
print(f"[WS] 사용자 인증 실패 → close(4001)")
print(f"[WS] 채팅방 없음: room_id={room_id} → close(4004)")
print(f"[WS] 참여자 아님: user_id={user_id}, seller={room['seller_id']}, buyer={room['buyer_id']} → close(4003)")
print(f"[WS] 연결 수락: user_id={user_id}, room_id={room_id}")
```

REST API는 정상(200)인데 WebSocket만 403인 경우 유력한 원인:
1. `verify_supabase_jwt`가 HTTPException을 raise → `except Exception`에 잡혀 None 반환 → close(4001) → 403
2. `chat_rooms` 테이블에 해당 room_id 없음 → close(4004) → 403
3. user_id가 seller_id/buyer_id 어느 쪽에도 없음 → close(4003) → 403

로그에서 `[WS AUTH] 인증 실패: HTTPException: ...` 패턴이 보이면 `verify_supabase_jwt` 내부 문제다.
WebSocket 핸들러는 FastAPI의 예외 처리 미들웨어를 거치지 않으므로 HTTPException도 일반 예외로 전파된다.

---

## 주의사항 & 함정

- **한글 IME 조합 중 Enter 중복 전송 버그**: `onKeyDown`에 `e.nativeEvent.isComposing` 체크를 반드시 추가한다. 없으면 한글 마지막 글자가 조합 완료 전에 handleSend가 호출되어 중복 전송된다.
  ```tsx
  onKeyDown={(e) => {
    if (e.nativeEvent.isComposing) return;  // 한글 IME 조합 중 전송 방지
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }}
  ```

- `useWebSocketChat`의 `connect` 함수는 `roomIdRef`를 사용하므로 deps 배열이 비어있다. roomId 변경은 useEffect에서 `retryCountRef.current = 0` 후 `connect()` 재호출로 처리.
- WS 언마운트 시 `ws.onclose = null` 먼저 설정 후 `ws.close()` — 그렇지 않으면 onclose가 재연결 타이머를 등록해 메모리 누수 발생.
- `WebSocketMessage` 인터페이스는 `types/chat.ts`의 `Message` 인터페이스와 필드가 동기화되어야 한다. 백엔드에서 `Message` 모델에 컬럼이 추가되면 양쪽 모두 수정 필요: `types/chat.ts`의 `Message`, `hooks/useWebSocketChat.ts`의 `WebSocketMessage`, 그리고 `hooks/useChat.ts`의 `incomingMessage` 객체 생성부.
- `useMessagesWithWebSocket`에서 WS 수신 메시지를 캐시에 추가할 때 `id` 중복 체크 필수 — 서버가 동일 메시지를 두 번 보낼 경우 대비.
- 전송 버튼 disabled를 `!isConnected`로 설정 — WS 미연결 상태에서 전송 시도 방지.

### 새로고침 후 채팅방 목록 빈 배열 고정 버그 (검증됨)

`useChatRooms`에 `enabled` 조건이 없으면 Supabase auth 세션 복구 전에 쿼리가 실행돼 401 → 빈 배열로 고정된다.
반드시 `useAuthStore`의 `user`를 가져와 `enabled: !!user`를 추가한다. `retry: 2`, `retryDelay: 1000`도 함께 설정해 인증 복구 시간을 확보한다.

```typescript
// hooks/useChat.ts
import { useAuthStore } from '@/store/authStore';

export function useChatRooms() {
  const { user } = useAuthStore();

  const query = useQuery({
    queryKey: ['chatRooms'],
    queryFn: () => api.get<SuccessResponse<ChatRoom[]>>('/chat/rooms'),
    enabled: !!user,   // user가 null→object로 변경 시 자동으로 쿼리 실행
    retry: 2,
    retryDelay: 1000,
  });
  // ...
}
```

### WebSocket 토큰 없을 때 조기 차단 패턴 (검증됨)

토큰이 null이면 연결을 시도하지 않는다. 시도하면 백엔드가 code 4001로 즉시 종료하고 재시도 3회 낭비 발생.
또한 `onclose`에서 code 4001 수신 시 재시도하지 않고 즉시 에러 메시지를 세팅한다.
재시도 횟수 초과 시에도 에러 메시지를 세팅해 사용자에게 피드백을 제공한다.

```typescript
// connect() 내부 — 토큰 획득 후
if (!token) {
  setError('인증 토큰이 없어 WebSocket에 연결할 수 없습니다.');
  return;
}

// onclose 핸들러
ws.onclose = (event) => {
  setIsConnected(false);
  wsRef.current = null;
  if (event.code === 4001) {
    setError('인증에 실패하여 채팅 연결이 종료되었습니다.');
    return;
  }
  if (roomIdRef.current && retryCountRef.current < MAX_RETRY) {
    retryCountRef.current += 1;
    retryTimerRef.current = setTimeout(() => connect(), RETRY_DELAY_MS);
  } else if (retryCountRef.current >= MAX_RETRY) {
    setError('서버 연결에 실패했습니다. 페이지를 새로고침해주세요.');
  }
};
```

### WebSocket 다중 탭 send_private_message (검증됨)

`ConnectionManager.active_user_connections` 는 `dict[str, set[WebSocket]]` 로 같은 user_id 가 여러 탭/디바이스로 접속해도 모두에 broadcast 가능하다. `send_private_message` 는 set 의 모든 ws 에 try/except 로 전송하고 끊긴 ws 는 자동 정리한다. 단일 ws 매핑(`dict[str, WebSocket]`)으로 두면 두 번째 탭이 첫 번째 탭의 매핑을 덮어쓰고 첫 번째 탭은 alternative_partners_suggestion 같은 개별 알림을 받지 못한다.

```python
# connection_manager.py
self.active_user_connections: dict[str, set[WebSocket]] = {}

async def send_private_message(self, user_id, message):
    ws_set = self.active_user_connections.get(user_id)
    if not ws_set:
        return
    dead = []
    for ws in list(ws_set):
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        ws_set.discard(ws)
```

### 합의 자동 주문 검증 + 멱등성 (검증됨)

`chat_ws.py _handle_consensus` 가 LLM 의 `extracted` 필드를 신뢰하기 전 검증을 모두 통과해야 `create_order` 진입한다:
1. `product`: 비어있지 않은 문자열
2. `quantity`: int > 0 AND ≤ `_MAX_QUANTITY`(10_000_000) — LLM 환각/오타 비현실적 큰 값 차단 (Postgres int4 max 보호)
3. `price_per_unit`: int > 0 AND ≤ `_MAX_PRICE_PER_UNIT`(100_000_000원/단위)
4. `delivery_date`: `date.fromisoformat(...)` 파싱 가능 + 오늘 이후

검증 실패 시 `[SYSTEM]` 메시지를 messages 테이블에 INSERT 하고 broadcast: `"⚠️ AI가 합의를 감지했지만 주문 정보(수량/단가/납기일)가 불완전해 자동 생성을 보류했습니다. ({reason})"` — 사용자가 무엇이 문제인지 알 수 있도록 reason 포함.

멱등성 다층 방어:
1. **signature 비교** (`_handle_consensus` 진입 직후) — `f"{buyer_id}|{seller_id}|{product}|{delivery_date}"` 가 직전 처리된 합의와 동일하면 즉시 skip (False 반환). 같은 채팅방에서 다른 거래 합의는 정상 처리.
2. **DB 중복 주문 확인** (`_check_recent_duplicate_order`) — 동일 (buyer_id, seller_id, product_id, delivery_date) 조합 주문이 최근 1시간 이내 존재하면 skip + 시스템 메시지.
3. **낙관적 락** (C-3) — `_handle_consensus` 진입 전에 `consensus_handled=True` 마킹. 같은 합의에 대한 동시 LLM 호출/시스템 메시지 중복 방지. 검증 실패/예외 시 호출처 try/except 에서 `consensus_handled=False` 로 되돌림.

`should_analyze` 쿨다운 정책:
- 빈 상태: True
- `consensus_handled=True` AND elapsed ≤ 60s: False (디바운스 — 같은 거래 즉각 재분석 방지, LLM 비용 절감)
- `consensus_handled=True` AND 60s < elapsed ≤ 1800s: True (signature 비교는 `_handle_consensus` 가 담당 → 같은 거래는 거기서 skip, 다른 거래는 처리)
- elapsed > 1800s: 일반 status 분기 (general 60s, negotiating 10s, consensus/rejected 항상 True)

`last_analysis` 는 `cachetools.TTLCache(maxsize=10000, ttl=3600)` 사용 (메모리 누수 방지). `cachetools>=5.3.0` 는 `backend/requirements.txt` 의 정식 의존성 — 운영에서 dict fallback 으로 떨어지지 않도록 venv 에 설치 필수 (2026-04-29 검증). `chat_ws.py` 의 try/except ImportError fallback 은 dev 환경 안전망으로 유지하되, 운영 startup 로그에 `[WS] cachetools 미설치` 가 보이면 venv 에 미설치된 상태이니 `pip install -r requirements.txt` 재실행 필요.

```python
# C-3 낙관적 락 패턴 (chat_ws.py)
if status == "consensus":
    last_analysis[room_id] = {..., "consensus_handled": True, "consensus_signature": sig}  # lock acquire
    try:
        handled = await _handle_consensus(room_id, result)
        if not handled:
            last_analysis[room_id] = {..., "consensus_handled": False, ...}  # release on logical fail
    except Exception:
        last_analysis[room_id] = {..., "consensus_handled": False, ...}  # release on exception
```

### 시스템 메시지 DB INSERT (검증됨)

`messages.sender_id` 는 `NOT NULL` 이므로 시스템 메시지도 sender_id 가 필요하다. `chat_service.send_system_message(room_id, content, sender_id)` 가 fallback sender_id (chat_room.seller_id 사용)로 INSERT 하고 content 앞에 `[SYSTEM]` prefix 를 붙여 시스템 메시지임을 표시한다. `is_read=True` 로 설정해 읽음 처리에서 제외한다.

broadcast payload 에는 INSERT 된 message_id 와 created_at 을 포함하여 프론트가 메시지 추적 가능하도록 한다:
```python
payload = {"type": "system", "content": ..., "room_id": ..., "id": message_id, "created_at": ...}
```

### `_broadcast_system_message` sender_id_fallback 가드 (검증됨)

`chat_ws.py _broadcast_system_message(room_id, content, sender_id_fallback)` 의 `sender_id_fallback = seller_id or buyer_id` 가 둘 다 빈 문자열이면 `UUID("")` 변환에서 `ValueError` 가 발생해 DB INSERT 가 무조건 실패한다. messages.sender_id 는 NOT NULL FK 이므로 빈 값으로는 INSERT 불가하다. 두 단계 가드를 적용한다.

```python
sender_clean = (sender_id_fallback or "").strip()
if not sender_clean:
    print(f"[system_msg] sender_id_fallback 비어있음 → DB INSERT skip ...")
else:
    try:
        sender_uuid = UUID(sender_clean)
    except (ValueError, TypeError) as e:
        print(f"[system_msg] sender_id_fallback UUID 변환 실패 → DB INSERT skip ...")
    else:
        # DB INSERT 진행
        message = await chat_service.send_system_message(...)

# 어떤 경로든 broadcast 는 항상 시도 (채팅 흐름 우선)
await manager.broadcast(room_id, payload)
```

핵심: **DB INSERT skip 시에도 broadcast 는 반드시 진행** — 시스템 메시지 자체는 사용자에게 전달되어야 한다. 단, payload 에 `id`/`created_at` 필드는 빠진다 (프론트가 옵셔널로 처리).

### analyze_chat_consensus 권한 검증 (검증됨)

`analyze_chat_consensus(room_id, last_n_messages, caller_user_id)` 의 `caller_user_id` 가 chat_room 의 buyer_id/seller_id 와 일치하지 않으면 fallback `{"status": "general", ...}` 반환. WebSocket 핸들러에서 caller_user_id 를 항상 전달하도록 `analyze_chat_consensus(room_id, 10, user_id)` 호출.

> **모듈 위치 (PR 3, 2026-05-04)**: `analyze_chat_consensus` 의 본문은 `backend/app/services/agent/tools/chat.py` 로 이동했다. `@tool` 데코레이터 미부착 → ToolRegistry 미등록 (LLM 도구 아님). chat_ws.py 호환을 위해 `from app.services.agent_tools import analyze_chat_consensus` 는 re-export shim 으로 그대로 동작. 마찬가지로 `get_chat_rooms` / `get_chat_messages` / `send_chat_message` (3 LLM 도구) 도 같은 모듈로 이동 + `@tool(groups=("chat",))` 등록 → orchestrator 의 `TOOLS_CHAT` 은 registry import.

### 대체 거래처 제안 (alternative_partners_suggestion) 풀 페이로드 패턴 (검증됨)

백엔드 `chat_ws.py _handle_rejected` 가 보내는 payload 전체를 프론트에서 사용한다:
`{type, message, alternatives: AlternativePartner[], category}`. 단순 배너만 띄우면 dead-data가 된다.

```typescript
// types/chat.ts — 백엔드 find_alternative_partners alternatives 항목 매칭
export interface AlternativePartner {
  user_id: string;
  name: string;
  company_name?: string;
  trade_count?: number;
  last_trade_date?: string | null;
  stock_quantity?: number | null;
  price_per_unit?: number | null;
  unit?: string;
  product_name?: string;
  category?: string;
  phone?: string;
  email?: string;
}

// hooks/useWebSocketChat.ts — WebSocketMessage에 alternatives, category 필드 정의
import type { AlternativePartner } from '@/types';
export interface WebSocketMessage {
  type: 'message' | 'error' | 'system' | 'alternative_partners_suggestion';
  // ...기존 필드
  message?: string; // error / suggestion 공통 표시용
  alternatives?: AlternativePartner[]; // suggestion 전용
  category?: string;
}
```

채팅 페이지 배너:
- 상단 1~3개 카드 미리보기 (`alternatives.slice(0, 3)`)
- 각 카드 클릭 → `useCreateChatRoom` 으로 새 채팅방 개설 → `setSelectedRoomId(newRoomId)` + `router.push('/{seller|buyer}/chat?room_id=...')`
- 우측 X 버튼으로 닫기 (`suggestionDismissed` 로컬 state)
- 새 suggestion 도착 시 useEffect로 `setSuggestionDismissed(false)` 자동 초기화

```tsx
// 닫힘 + 새 suggestion 자동 초기화
const [suggestionDismissed, setSuggestionDismissed] = useState(false);
useEffect(() => {
  if (alternativePartnersSuggestion) setSuggestionDismissed(false);
}, [alternativePartnersSuggestion]);
const visibleSuggestion = !suggestionDismissed ? alternativePartnersSuggestion : null;
const previewAlternatives = (visibleSuggestion?.alternatives ?? []).slice(0, 3);

// 클릭 핸들러
const handleAlternativeClick = async (partner: AlternativePartner) => {
  if (!partner.user_id || createChatRoom.isPending) return;
  const res = await createChatRoom.mutateAsync({ partner_user_id: partner.user_id });
  setSuggestionDismissed(true);
  router.push(`/seller/chat?room_id=${res.data.id}`);
  setSelectedRoomId(res.data.id);  // 같은 페이지 내 라우팅이므로 직접 갱신
};
```

### open_chat_room 보안 검증 (검증됨)

`agent_tools.open_chat_room(user_id, partner_user_id)` 의 보안 검증은 두 가지만 수행:
1. self-chat 거부 (`user_id == partner_user_id` → `self_chat_not_allowed`)
2. partner 존재 + `deleted_at IS NULL` 확인 (없으면 `partner_not_found`)

기존에 있던 24h 5건 throttle (`rate_limited`) 은 dead code 였다 — 기존 방이 항상 `existing.data` 검색에서 잡히므로 동일 (seller, buyer) 페어가 24시간 내 5번씩 새 방을 만드는 시나리오 자체가 발생 불가. 제거함.

### send_chat_message 거래처+주문 2단계 disambiguation (검증됨, 2026-05-03)

AI 도우미가 "test4한테 옥수수 50kg 배송 완료라고 보내줘" 같은 발화를 받으면 어느 채팅방에 보내야 할지 모호했다 (test4 와 옥수수 40kg 주문방 + 옥수수 50kg 주문방이 동시에 있을 수 있음). `agent_tools.send_chat_message` 를 V1(legacy) / V2(신규) 두 시그니처를 모두 받는 구조로 확장:

```python
def send_chat_message(
    room_id: str = "",          # V1: 직접 지정 시 그대로 발송
    sender_id: str = "",        # 서버에서 _fix_id_params 가 user_id 로 강제 주입
    content: str = "",          # legacy alias for message
    partner_user_id: str = "",  # V2: 거래처 사용자 UUID
    order_hint: Optional[dict] = None,  # {product_name?, quantity?, status?, recent?}
    message: str = "",          # V2: 메시지 본문 (content 보다 우선)
) -> dict
```

동작 흐름:
1. `room_id` 가 유효 UUID → 즉시 발송 (V1 경로, 호환)
2. `partner_user_id` + (선택) `order_hint` 로 후보 방 검색 (V2 경로)
3. 후보 1개 → 즉시 발송 + `matched_room` 정보 반환
4. 후보 ≥ 2개 → **발송 보류** + `{success: False, needs_confirmation: True, candidates: [...], message_preview}`
5. 후보 0개 → `order_id IS NULL` 일반 채팅방 fallback. 그것도 없으면 `{success: False, error: "no_chat_room"}` (open_chat_room 으로 먼저 만들라는 안내)

후보 검색 (`_resolve_chat_room_candidates`):
- `chat_rooms.deleted_at` 컬럼은 2026-05-06 마이그레이션으로 추가됨. 후보 검색 쿼리에는 `.is_("deleted_at", None)` 필터를 추가해 주문 취소된 방을 제외하는 것이 권장된다 (필터 누락 시 LLM 이 취소된 거래의 옛 채팅방을 후보로 제시할 수 있음).
- 양방향 매칭: `or_("and(seller_id.eq.A,buyer_id.eq.B),and(seller_id.eq.B,buyer_id.eq.A)")` UUID 만 들어가므로 인용 불필요
- orders 임베딩으로 status / order_items / products(name, unit) 조회
- `orders.deleted_at IS NOT NULL` 또는 `status='CANCELLED'` 인 방은 주문 정보 무시 (일반방으로 격하)
- order_hint 매칭: `product_name` ilike 부분일치, `quantity` 정확일치, `status` 정확일치(uppercase)
- `recent=True` 시 `last_message_at DESC` 첫 1건만

핵심 — `chat_node` 의 조기 종료 분기 (`if '"success": true' in result_content.lower(): return ...`) 와의 정합성:
- 다중 매칭 시 **반드시 `success: False`** 로 반환해야 LLM 이 후보 리스트를 사용자에게 풀어 질문하도록 흐름이 이어진다. `success: True` 로 두면 chat_node 가 즉시 "메시지를 성공적으로 전송했습니다!" 로 잘못 답한다.

`_fix_id_params` 정합성:
- `partner_user_id` 는 user_id 강제 교정 루프(`("seller_id", "user_id", "buyer_id", "sender_id")`) 에 안 잡히므로 LLM 이 추론한 partner UUID 가 그대로 보존됨 (open_chat_room 과 동일 정책).
- `room_id` 가 비유효 UUID 면 `tool_input.pop("room_id", None)` 로 제거되어 V2 경로로 자동 fallback — 새 default `room_id=""` 와 호환.

도구 등록 (`orchestrator.py` `TOOLS_INVENTORY` + `TOOLS_CHAT` 두 군데):
```json
{
  "name": "send_chat_message",
  "parameters": {
    "type": "object",
    "properties": {
      "partner_user_id": {"type": "string"},
      "order_hint": {
        "type": "object",
        "properties": {
          "product_name": {"type": "string"},
          "quantity": {"type": "integer"},
          "status": {"type": "string"},
          "recent": {"type": "boolean"}
        }
      },
      "message": {"type": "string"},
      "room_id": {"type": "string", "description": "(legacy) ..."},
      "sender_id": {"type": "string", "description": "(legacy) ..."},
      "content": {"type": "string", "description": "(legacy) ..."}
    },
    "required": ["message"]
  }
}
```

`required` 가 `message` 단 1개로 줄어든 점이 핵심 — LLM 이 partner_user_id 만 알고 room_id 를 모를 때도 호출 가능. 단 partner_user_id 도 room_id 도 없으면 `error: "missing_room_or_partner"` 로 실패.

### 시스템 메시지 prefix 화이트리스트 패턴 (검증됨)

`msg.content.startsWith('[') && msg.content.includes(']')` 같은 느슨한 매칭은 사용자가 보낸 "[중요]"
같은 일반 텍스트도 시스템 pill로 잘못 표시한다. `constants/chat.ts` 에 prefix 화이트리스트를 정의해 사용한다.

```typescript
// constants/chat.ts
export const SYSTEM_MESSAGE_PREFIXES = ['[견적 요청]', 'AI가', '⚠️', '🤖'] as const;
export function isSystemMessageContent(content: string): boolean {
  return SYSTEM_MESSAGE_PREFIXES.some((p) => content.startsWith(p));
}

// 채팅 페이지에서 — 레거시 호환용 (message_type 없는 옛 메시지)
import { isSystemMessageContent } from '@/constants/chat';
const isSystem = isSystemMessageContent(msg.content);
```

WebSocket `lastMessage.type === 'system'` (실시간 system broadcast)는 별도 분기 — 백엔드 `chat_ws.py` 의
`{"type":"system", "content":"AI가 거래 합의를 감지하여 ..."}` 는 prefix `AI가` 로 시작하므로
`useMessagesWithWebSocket` 캐시에 들어가 같은 화이트리스트로 자연스럽게 처리된다.

### 주문 협상 ↔ 채팅 양방향 연결 (검증됨, 2026-04-27)

backend 가 message에 `message_type` + `metadata` 를 함께 broadcast하므로 프론트는 prefix 매칭 없이
`message_type` 으로 분기 렌더한다. 레거시 호환만 prefix 화이트리스트를 사용한다.

#### 메시지 타입 정의 (types/chat.ts)

```typescript
export type MessageType =
  | 'TEXT'
  | 'SYSTEM'
  | 'COUNTER_OFFER'
  | 'OFFER_ACCEPTED'
  | 'OFFER_REJECTED'
  | 'ORDER_STATUS'
  | 'ORDER_CANCELLED';

// metadata 는 message_type별 형태가 다름 — 모든 키 optional
export interface MessageMetadata {
  order_id?: string;
  order_number?: string;
  total_amount?: number;
  offer_id?: string;
  proposed_total_amount?: number;
  from_role?: 'SELLER' | 'BUYER';
  notes?: string;
  status?: 'PENDING' | 'ACCEPTED' | 'REJECTED' | 'SUPERSEDED';
  accepted_amount?: number;
  from_status?: string;
  to_status?: string;
  reason?: string;
  cancelled_by?: string;
  [key: string]: unknown;
}

export interface Message {
  // ... 기존 필드
  message_type?: MessageType;
  metadata?: MessageMetadata | null;
}
```

`useWebSocketChat`의 `WebSocketMessage` 인터페이스에도 `message_type`, `metadata` 필드를 추가하고,
`useMessagesWithWebSocket`의 `incomingMessage` 객체 생성 시 두 필드를 함께 전달해야 캐시에 정상 반영됨.

#### MessageBubble — message_type별 분기 렌더 (components/chat/MessageBubble.tsx)

`switch (type)` 으로 단일 컴포넌트에서 분기. 본인/상대 판별은 **`sender_id === user.id` 우선**
(metadata.from_role 만으로는 같은 역할 두 사용자 구분 불가).

#### MessageBubble currentUserId prop 패턴 (검증됨)

`useAuthStore` 는 Zustand persist 사용으로 첫 렌더 시점에 user 가 null 일 수 있다.
이 상태에서 `isMine` 이 false 로 고정되면 본인 메시지가 모두 왼쪽에 표시되는 버그가 발생한다
(새로고침하면 정상 — persist 하이드레이션 완료 후이므로).

해결: 부모 페이지에서 `user?.id` 를 `currentUserId` prop 으로 직접 내려준다.
MessageBubble 내부에서는 `currentUserId ?? user?.id` 로 우선순위 처리.

```tsx
// MessageBubble props
interface MessageBubbleProps {
  message: Message;
  currentUserId?: string;
}

export default function MessageBubble({ message, currentUserId }: MessageBubbleProps) {
  const { user } = useAuthStore();
  const effectiveUserId = currentUserId ?? user?.id;
  const isMine = !!effectiveUserId && message.sender_id === effectiveUserId;
  // ...
}

// seller/chat/page.tsx, buyer/chat/page.tsx — 호출부
<MessageBubble key={msg.id} message={msg} currentUserId={user?.id} />
// 시스템 메시지 변환 분기에도 동일하게 prop 전달
<MessageBubble key={msg.id} message={{ ...msg, message_type: 'SYSTEM' }} currentUserId={user?.id} />
```

부모 컴포넌트는 `useAuthStore` 호출 후 React Query 가 `user` 변경 시 자동 리렌더되므로,
prop 으로 흘려주는 패턴이 안정적이다.

| type | 렌더 |
|---|---|
| `TEXT` | 일반 말풍선 (mine: bg-primary-600 text-white / 상대: bg-gray-100) |
| `SYSTEM` | 가운데 회색 안내 박스. content의 `[SYSTEM]` prefix 자동 제거. |
| `COUNTER_OFFER` | amber 강조 카드 + DollarSign 아이콘 + 큰 글씨 amount + status 배지. 상대 PENDING이면 수락/거절 버튼 (useAcceptCounterOffer/useRejectCounterOffer) |
| `OFFER_ACCEPTED` | 가운데 초록 카드 + Check + "{amount}원에 협상 수락" |
| `OFFER_REJECTED` | 가운데 회색 카드 + X + "협상가 거절" |
| `ORDER_STATUS` | 가운데 파란 박스 + Package + StatusBadge from → to |
| `ORDER_CANCELLED` | 가운데 빨간 카드 + Ban + "주문이 취소됐습니다" + reason |

채팅 페이지에서는 `MessageBubble` 한 줄로 호출 + 레거시 호환 분기:
```tsx
{messages.map((msg) => {
  // 옛 메시지 (message_type 없음) 중 prefix 패턴은 SYSTEM 으로 변환
  if (!msg.message_type && isSystemMessageContent(msg.content)) {
    return <MessageBubble key={msg.id} message={{ ...msg, message_type: 'SYSTEM' }} />;
  }
  return <MessageBubble key={msg.id} message={msg} />;
})}
```

#### useSubmitCounterOfferViaChat 훅 (hooks/useChat.ts)

채팅 입력창의 "가격 제시" 버튼이 호출하는 mutation. 백엔드 `POST /chat/rooms/{room_id}/counter-offer`.
chat_room.order_id 가 없으면 백엔드가 400 으로 거부 → 호출 측 가드 필요 (PriceOfferPopover 가 disable).

```typescript
export function useSubmitCounterOfferViaChat(roomId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CounterOfferCreate) => {
      if (!roomId) throw new Error('채팅방이 선택되지 않아 협상가를 제시할 수 없습니다.');
      return api.post<SuccessResponse<CounterOffer>>(
        `/chat/rooms/${roomId}/counter-offer`,
        payload
      );
    },
    onSuccess: (res) => {
      const orderId = res.data.order_id;
      queryClient.invalidateQueries({ queryKey: ['orders'] });
      if (orderId) {
        queryClient.invalidateQueries({ queryKey: ['order', orderId] });
        queryClient.invalidateQueries({ queryKey: ['negotiation', orderId] });
      }
      if (roomId) queryClient.invalidateQueries({ queryKey: ['messages', roomId] });
      queryClient.invalidateQueries({ queryKey: ['chatRooms'] });
    },
  });
}
```

#### WS 수신 시 주문/협상 캐시 자동 invalidate

`useMessagesWithWebSocket` 의 useEffect에서 incoming message의 `message_type`이
`COUNTER_OFFER`/`OFFER_ACCEPTED`/`OFFER_REJECTED`/`ORDER_STATUS`/`ORDER_CANCELLED`/`SYSTEM` 중 하나면
`['orders']`, `['order', metadata.order_id]`, `['negotiation', metadata.order_id]`,
**그리고 `['messages', roomId]`** 캐시를 invalidate.
**같은 사용자가 다른 탭에서 주문 페이지 열어둔 경우 자동 동기화** 효과.

`['messages', roomId]` invalidate 가 반드시 필요한 이유 (검증됨, 2026-04-27):
백엔드는 협상가 accept/reject/SUPERSEDED 시 같은 `offer_id` 를 가진 **이전** `messages` 행의
`metadata.status` 도 함께 ACCEPTED/REJECTED/SUPERSEDED 로 동기화한다. 그러나 WebSocket 은
**새 메시지 INSERT 만** broadcast 하고, **기존 메시지의 metadata UPDATE 는 알리지 않는다**.
따라서 클라이언트가 messages 쿼리를 다시 fetch 하지 않으면 stale 데이터 (이전 카드 status='PENDING')
를 그대로 보여주고, MessageBubble 의 수락/거절 버튼이 사라지지 않는다.

```typescript
if (msgType && ORDER_RELATED_TYPES.includes(msgType)) {
  // ...orders/order/negotiation invalidate
  queryClient.invalidateQueries({ queryKey: ['messages', roomId] });  // ← 필수
}
```

#### 새 PENDING 카드 도착 시 낙관적 SUPERSEDED 마킹 (검증됨, 2026-05-03)

`['messages', roomId]` 를 invalidate 만 해도 결국 refetch 가 정답을 가져오지만, **네트워크 RTT 동안**
이전 PENDING 카드가 그대로 노출돼 본인이 방금 새로 제시한 카드 위쪽에 수락/거절 버튼이 잠깐 보이는
문제가 있다 (issue.md #1: "새로고침하면 사라지는데 새로고침 전에도 안 뜨게 해달라"). 사용자 입장에서는
"본인 제안인데 본인이 수락 버튼을 누를 수 있는 상태"가 되어 시스템적으로 모순되어 보인다.

해결: `useMessagesWithWebSocket` 의 WS 수신 useEffect 에서 새 메시지를 캐시에 넣을 때, **같은 useEffect
안의 `setQueryData` 안에서** 이전 동일 카드들 (`message_type` 일치 + `metadata.order_id` 일치 +
`metadata.status === 'PENDING'`) 의 status 를 'SUPERSEDED' 로 미리 바꿔준다. invalidate refetch 는 그대로
유지 — 백엔드 정식 status 값 (REPLACED/SUPERSEDED 등) 으로 최종 동기화 책임. 즉 **낙관적 갱신 + 서버
권위 갱신** 이중 구조.

대상 message_type:
- `COUNTER_OFFER` — 새 협상가 제시 시 이전 PENDING 협상가 모두 SUPERSEDED
- `DELIVERY_DATE_CHANGE` — 새 납품일 변경 요청 시 이전 PENDING 변경 요청 모두 SUPERSEDED

```typescript
const incomingType = incomingMessage.message_type;
const incomingMeta = incomingMessage.metadata;
const incomingOrderId = incomingMeta?.order_id;
const incomingStatus = incomingMeta?.status;
const supersedesPrevious =
  !!incomingOrderId &&
  incomingStatus === 'PENDING' &&
  (incomingType === 'COUNTER_OFFER' || incomingType === 'DELIVERY_DATE_CHANGE');

queryClient.setQueryData(['messages', roomId], (old) => {
  if (!old) return { data: [incomingMessage] };
  const exists = old.data.some((m) => m.id === incomingMessage.id);
  const transformed = supersedesPrevious
    ? old.data.map((m) => {
        if (m.id === incomingMessage.id) return m;
        if (m.message_type !== incomingType) return m;
        const mMeta = m.metadata;
        if (!mMeta || mMeta.order_id !== incomingOrderId) return m;
        if (mMeta.status !== 'PENDING') return m;
        return { ...m, metadata: { ...mMeta, status: 'SUPERSEDED' as const } };
      })
    : old.data;
  if (exists) return { ...old, data: transformed };
  return { ...old, data: [...transformed, incomingMessage] };
});
```

주의: ACCEPTED/REJECTED 메시지(`OFFER_ACCEPTED`, `OFFER_REJECTED`, `DELIVERY_DATE_ACCEPTED`,
`DELIVERY_DATE_REJECTED`)는 별도 status 마킹이 필요 없다 — 이쪽은 백엔드 mutation 의 onSuccess
broad invalidate (`['messages']`) 가 충분히 빠르게 동작하고, 무엇보다 새 메시지 자체가 PENDING 이 아닌
독립 카드(가운데 정렬)라 `supersedesPrevious` 조건에 안 걸린다. 즉 이 낙관적 갱신은 **새 PENDING
제안이 도착해서 이전 PENDING 을 묻어버리는 케이스만** 다룬다.

QueryClient 의 `staleTime: 60_000` (`components/providers/QueryProvider.tsx`) 도 invalidate 의 동작에는
영향이 없다 (invalidateQueries 는 active query 의 staleTime 무관 refetch). 단지 refetch RTT 동안 잠깐의
stale UI 가 노출될 뿐이고, 그 윈도우를 이 낙관적 마킹이 메운다.

#### counter-offer mutation onSuccess 에서 broad messages invalidate (검증됨)

`useSubmitCounterOffer` / `useAcceptCounterOffer` / `useRejectCounterOffer` (`useOrders.ts`) 의
onSuccess 에서도 `['messages']` 를 broad 하게 invalidate 해야 한다. 이 mutation 들은 roomId 를
모르므로 (`['messages', roomId]` 가 아닌) `['messages']` 로 모든 채팅방 메시지를 함께 무효화한다.

`useSubmitCounterOfferViaChat` (`useChat.ts`) 도 같은 이유로 `['messages', roomId]` 대신
`['messages']` (broad) 로 변경됨 — 동일 사용자가 다른 채팅방을 열어둔 탭도 함께 갱신.

```typescript
// hooks/useOrders.ts — 세 mutation 모두
onSuccess: () => {
  queryClient.invalidateQueries({ queryKey: ['orders'] });
  queryClient.invalidateQueries({ queryKey: ['order', orderId] });
  queryClient.invalidateQueries({ queryKey: ['negotiation', orderId] });
  queryClient.invalidateQueries({ queryKey: ['messages'] });  // ← broad
}
```

#### MessageBubble race condition 가드 (검증됨)

`canAct = !isMine && offerStatus === 'PENDING'` 으로 버튼 자체는 status 변경 시 사라지지만,
fetch race 또는 stale 카드 잠재 클릭 대비로 onClick 핸들러 안에서도 한 번 더 status 검증한다.

```typescript
const handleAccept = () => {
  if (!offerId || !orderId) return;
  if (offerStatus !== 'PENDING') return;  // race condition 가드
  acceptMutation.mutate({ offerId });
};
```

#### OrderContextBanner — 헤더 아래 주문 요약 배너 (components/chat/OrderContextBanner.tsx)

`selectedRoom?.order_id` 가 있을 때만 렌더. `useOrder(orderId)` 로 주문 정보 fetch.
- 상품명 첫 항목 + "외 N건"
- StatusBadge
- 주문번호 + 총액
- 우측 "이력" 토글 버튼 → 펼치면 `<NegotiationHistory orderId={...} />` (`components/chat/NegotiationHistory.tsx`) 협상 이력 타임라인 노출
- 우측 "주문 상세 보기" 버튼 → `onOpenOrder(id)` 콜백 (페이지에서 `router.push('/{role}/orders?id=...')`)

이력 토글 상태는 컴포넌트 내부 `useState(false)` (전역 X). 모바일/데스크톱 모두 기본 접힘 → 닫힌 상태에서는 기존 1줄 layout 유지. 모바일 작은 폭에서는 버튼 라벨 ("이력"/"주문 상세 보기")이 `sm:` 미만에서 자동 축약.

주문이 없거나 fetch 실패 시 배너 자동 숨김 (요구사항). props 시그니처는 `(orderId, role, onOpenOrder)` 그대로 — 호출부 (seller/chat/page.tsx, buyer/chat/page.tsx) 변경 불필요.

#### NegotiationHistory — 채팅 배너 안 협상 타임라인 (components/chat/NegotiationHistory.tsx)

`OrderContextBanner` 의 이력 토글이 펼쳐졌을 때만 렌더되는 **읽기 전용** 타임라인.
`components/common/NegotiationHistory.tsx` 와 별도 — common 버전은 주문 상세 슬라이드 패널의 액션(수락/거절) 포함 풀 버전, **chat 버전은 액션 없음** (채팅 메시지의 `COUNTER_OFFER` 카드 = `MessageBubble` 가 동일 액션을 이미 제공하므로 중복 회피).

- 동일 훅 `useNegotiationHistory(orderId)` 재사용 — 캐시 공유 (queryKey: `['negotiation', orderId]`)
- 시간 역순. 빈 배열이면 미니 placeholder ("협상 이력이 없습니다.")
- 에러 시 `null` 반환 (조용히 숨김 — UX 우선)
- 좌측 세로 라인 + 상태별 색 dot (PENDING=노랑 / ACCEPTED=녹색 / REJECTED=빨강 / SUPERSEDED=회색) + 상대시간 표시 (`방금 전 / N분 전 / N시간 전 / N일 전`)
- 컴포넌트 내부 padding (`px-4 pb-3`) 만 적용 → 부모(배너) 가 외곽 컨테이너 책임

#### PriceOfferPopover — 채팅 입력창 가격 제시 버튼 (components/chat/PriceOfferPopover.tsx)

DollarSign 아이콘 버튼 + 외부 클릭으로 닫히는 팝오버 입력 폼. amount(필수, >0 정수) + notes(선택).
- room.order_id 가 없으면 비활성화 + tooltip 안내
- 제출 → `useSubmitCounterOfferViaChat(roomId).mutate(...)`
- 외부 클릭 감지: `useRef + mousedown` (drop-down 패턴과 동일)

채팅 페이지 입력창에 `<input>` 좌측에 배치:
```tsx
<div className="flex gap-2">
  <PriceOfferPopover roomId={selectedRoomId} orderId={linkedOrderId} currentTotal={linkedOrderTotal} />
  <input ... />
  <button onClick={handleSend}>...</button>
</div>
```

##### prefill 패턴 (US-2 협상 의도 감지 [등록] — 검증됨, 2026-05-04)

PriceOfferPopover 는 `prefill?: PriceOfferPrefill | null` + `onPrefillConsumed?: () => void` 두 prop 으로
외부에서 팝오버를 열고 입력값을 미리 채울 수 있다. 부모(채팅 페이지)는 prefill 객체 reference 를 갱신할 때마다
팝오버가 열리고 `amount` / `notes` 가 채워진다.

```tsx
// 채팅 페이지에서
const [draftPrefill, setDraftPrefill] = useState<PriceOfferPrefill | null>(null);

const handleAcceptDraft = (draft: NegotiationDraft) => {
  const total =
    draft.quantity && draft.unit_price && draft.quantity > 0 && draft.unit_price > 0
      ? draft.quantity * draft.unit_price
      : undefined;
  setDraftPrefill({ amount: total, notes: '...요약...' });
};

<PriceOfferPopover
  roomId={selectedRoomId}
  orderId={linkedOrderId}
  prefill={draftPrefill}
  onPrefillConsumed={() => setDraftPrefill(null)}
/>
```

내부 동작:
- `prefill` 변경 + `disabled === false` 면 `setIsOpen(true)` 자동 트리거
- `openedByPrefillRef` 로 한 번만 prefill 보존 — 사용자가 닫고 다시 열면 일반 초기화 동작 복귀
- `disabled` (orderId/roomId 없음) 일 때는 prefill 무시 (버튼 자체 비활성)

#### NegotiationDraftCard — 협상 의도 감지 카드 (US-2 — 검증됨, 2026-05-04)

평문 메시지에서 가격 협상 의도(품목/수량/단가)가 감지되면 발신자 본인의 메시지 아래 회색 박스로 노출된다.
**자동 등록 절대 X** — 사용자 [등록] 클릭 시 PriceOfferPopover prefill 흐름으로 분기.

WS 이벤트:
```jsonc
{
  "type": "negotiation_draft_detected",
  "message_id": "uuid",
  "room_id": "uuid",
  "target_user_id": "uuid (= sender_id)",
  "draft": { product_name, quantity, unit, unit_price, confidence, detected_at, dismissed_at }
}
```

타입 (`types/chat.ts`):
- `NegotiationDraft` — 백엔드 schemas/chat.py NegotiationDraft 와 1:1 매칭
- `MessageMetadata.draft_negotiation?: NegotiationDraft` — TEXT 메시지에만 채워짐

WS 수신 처리 (`useMessagesWithWebSocket`):
```ts
if (lastMessage.type === 'negotiation_draft_detected') {
  // 본인에게 온 이벤트만 처리 (target_user_id === user.id 가드)
  // 해당 message_id 의 messages 캐시에서 metadata.draft_negotiation 만 setQueryData 로 채움
  // 메시지 자체가 캐시에 없으면 fallback 으로 invalidate
  return;  // 일반 message 분기 진입 막기
}
```

표시 가드 (`MessageBubble` TEXT case):
- `isMine === true`
- `metadata.draft_negotiation` 존재
- `dismissed_at === null`
- 5분 안 (`NegotiationDraftCard` 내부 `setTimeout` 으로 자동 hide — 백엔드는 timeout 안 함)

[등록] / [무시]:
- `[등록]` → `onAcceptNegotiationDraft(draft)` → 부모가 `setDraftPrefill` 호출 → PriceOfferPopover 자동 오픈
- `[무시]` → `useDismissNegotiationDraft(roomId).mutate(messageId)` → PATCH `/chat/messages/{id}/dismiss-draft-negotiation`
  → onSuccess 시 messages 캐시의 해당 메시지 metadata 만 낙관적 업데이트 (전체 invalidate X)

새로고침 후 복원: 메시지 metadata.draft_negotiation 이 그대로 남아있으므로 5분 안 + dismissed null 이면 자동 재표시.

#### 주문 상세 → 채팅 이동 흐름 (양 페이지)

`buyer/orders` `seller/orders` 상세 슬라이드 액션 영역 첫 번째 버튼:
```tsx
const createChatRoom = useCreateChatRoom();
const handleOpenChat = async () => {
  if (!selectedOrder) return;
  const res = await createChatRoom.mutateAsync({
    partner_user_id: selectedOrder.seller_id, // buyer 페이지: seller_id, seller 페이지: buyer_id
    order_id: selectedOrder.id,
  });
  router.push(`/buyer/chat?room_id=${res.data.id}`);
};
```

채팅 페이지에서는 `searchParams.get('room_id')` 로 자동 선택 (기존 buyer 페이지 패턴 유지, seller 페이지에도 동일 추가).

반대로 채팅의 "주문 상세 보기" 버튼은 `/{role}/orders?id=...` 로 라우팅하고, 주문 페이지에서
`searchParams.get('id')` 로 `setSelectedOrderId` 자동 호출 → 슬라이드 패널 자동 오픈.

### 채팅 페이지 채팅방 목록 로딩/에러 상태 표시 패턴 (검증됨)

`useChatRooms()`에서 `isLoading`, `error`, `refetch`를 함께 destructure해 로딩 스피너와 에러+재시도 버튼을 표시한다.

현재(2026-05-03) 두 채팅 페이지(`seller/chat`, `buyer/chat`)는 인라인 리스트 대신 공통 컴포넌트
`<ChatRoomList />` 를 사용한다 (아래 "채팅 리스트 거래처별 그룹핑" 섹션 참조). 위 destructure 한
`isLoading` / `error` / `refetch` 는 그대로 props 로 흘려준다:

```tsx
const { data: roomsData, isLoading: roomsLoading, error: roomsError, refetch: refetchRooms } = useChatRooms();
const rooms = roomsData?.data ?? [];

<ChatRoomList
  rooms={rooms}
  myRole="SELLER"   // 또는 "BUYER"
  selectedRoomId={selectedRoomId}
  onSelectRoom={handleRoomSelect}
  isLoading={roomsLoading}
  error={roomsError}
  onRetry={refetchRooms}
/>
```

`<ChatRoomList />` 내부가 isLoading/error/empty/groups 분기를 모두 담당한다 — 페이지 쪽엔 분기 X.

### 채팅 리스트 거래처별 그룹핑 (검증됨, 2026-05-03)

같은 거래처와 N개의 주문방이 있을 때 채팅 리스트가 평면 N행으로 흩어지면 한 거래처의 전체 거래
상황을 파악하기 어렵다. 거래처(파트너) 단위로 그룹 헤더 + 하위 주문방 카드 N개로 묶어 렌더한다.

#### 컴포넌트 구조 (frontend/components/chat/)
- `ChatRoomList.tsx` — 검색 인풋 + 미읽 필터 토글 + 그룹 목록. 양쪽 페이지에서 공통 사용
- `ChatRoomGroup.tsx` — 거래처 단위 그룹 헤더 (펼침/접힘 토글, 펼침 기본값 true) + 하위 방
- `ChatRoomItem.tsx` — 단일 방 카드. order_id 유무로 Package(주문 채팅) / MessageSquare(일반 대화) 아이콘 분기. nested=true 면 좌측 보더 + 들여쓰기
  - **subLabel 결정 (2026-05-05)**: 주문방이면 `room.first_product_name ?? room.order_number ?? '주문 채팅'` 순으로 fallback. 같은 거래처 내 여러 주문방을 한눈에 구분하기 위함. 백엔드 `/chat/rooms` 응답이 `order_number`, `first_product_name` 을 포함해야 동작 (둘 다 `ChatRoom` 인터페이스에서 optional `string | null`).

#### 그룹핑 로직 (frontend/lib/chatGrouping.ts)
순수 함수 `groupChatRoomsByPartner(rooms, myRole)` 가 백엔드 호출 없이 클라이언트에서 묶는다.
**`useChatRooms()` 응답 (`ChatRoom[]`) 의 기존 필드만으로 충분** — 추가 fetch 불필요.

```typescript
export interface ChatRoomGroup {
  partnerUserId: string;          // = myRole==='SELLER' ? buyer_id : seller_id
  partnerName: string | null;     // 가장 최근 활동 방의 partner_name
  partnerCompany: string | null;  // 가장 최근 활동 방의 partner_company
  unreadTotal: number;            // 그룹 내 unread_count 합
  lastActivityAt: string | null;  // MAX(last_message_at)
  activeOrderCount: number;       // order_id 가 NULL 이 아닌 방 개수
  rooms: ChatRoom[];              // 그룹 내 방 목록 (lastActivityAt DESC)
}
```

정렬:
- 그룹 자체: `lastActivityAt DESC` (null 인 그룹은 가장 뒤)
- 그룹 내 방: `last_message_at` (없으면 `created_at`) DESC

partner_user_id 결정 규칙 — 페이지에서 `myRole` prop 으로 전달:
- seller 페이지: `myRole='SELLER'` → `room.buyer_id`
- buyer 페이지: `myRole='BUYER'` → `room.seller_id`

#### 검색 / 필터
- 검색: 거래처 이름 / 회사명 부분일치 (`includes`, 소문자 정규화) → 매칭 그룹 전체 표시
- 미읽 필터 토글: `unreadTotal > 0` 인 그룹만
- 두 조건은 AND. `useMemo` 로 rooms / search / unreadOnly / myRole 의존성에 캐시

#### 그룹 헤더 자동 펼침 (UX)
사용자가 어떤 그룹을 접어둔 상태에서 다른 화면(주문 상세 → 채팅 이동)이 그 그룹의 방으로
라우팅하면, 헤더 안에서 선택된 방이 안 보이는 함정이 생긴다. `ChatRoomGroup` 내부에서
`group.rooms.some(r => r.id === selectedRoomId)` 면 강제 펼침으로 처리한다 (`isExpanded = expanded || containsSelected`). 사용자가 명시적으로 접어둔 상태값(`expanded`) 자체는 유지하되,
선택된 방이 있을 동안만 임시로 펼쳐 보이는 패턴.

#### "일반 대화 vs 주문 채팅" 시각 구분
백엔드 데이터 모델은 그대로 두고 `room.order_id` 의 truthy 여부로 분기:
- order_id 있음 → Package 아이콘 + "주문 채팅" 라벨 (text-primary-500)
- order_id 없음 → MessageSquare 아이콘 + "일반 대화" 라벨 (text-gray-400)

상품명/주문번호 같은 풀 데이터는 OrderContextBanner 가 메시지 영역에서 별도로 보여주므로
리스트 카드는 가벼운 라벨만.

#### 상대 시각 표시 헬퍼
ChatRoomGroup 내부 `formatRelativeTime(iso)` — "방금 전 / N분 전 / N시간 전 / N일 전" / 7일 이상은 `M.D` 짧은 날짜.
NegotiationHistory 의 동일 패턴과 시그니처 통일.

#### 페이지 변경분
seller/chat, buyer/chat 페이지의 인라인 리스트 ~50줄을 `<ChatRoomList />` 한 줄 호출로 치환.
`useChatRooms` / `useMessagesWithWebSocket` / `useMarkAsRead` / `useSummarizeChat` 등 기존
훅·로직은 모두 그대로 유지 — 메시지 영역 / 헤더 / OrderContextBanner / 빠른 액션 popover 변경 없음.

### 거래처 상세 — 진행 중 채팅 카드 섹션 (US-3, 검증됨 2026-05-04)

거래처 상세(`PartnerDetailModal`) 안에 그 거래처와의 채팅방을 카드 형태로 노출. 채팅 페이지로 가지 않고도 그 거래처와 어떤 주문이 협상 중인지 한눈에 보여주기 위한 진입점.

#### 컴포넌트 (frontend/components/partners/PartnerChatRooms.tsx)
- props: `partnerUserId: string`, `myRole: 'SELLER' | 'BUYER'`, `onNavigate?: () => void`
- 데이터 — 옵션 A (클라이언트 필터):
  - `useChatRooms()` 전체를 받아 `myRole==='SELLER' ? room.buyer_id : room.seller_id === partnerUserId` 로 필터
  - 주문 요약(품목·수량·상태)은 `useOrders({ partner_user_id, limit: 200 })` 응답을 `Map<order_id, Order>` 로 만들어 `room.order_id` 와 매칭
  - 백엔드 변경 0. 채팅방 N 이 커지면 옵션 B(백엔드 partner 필터 쿼리) 로 전환
- "진행 중" 정의: `order_id` 가 있는 방은 `order.status` 가 `COMPLETED`/`CANCELLED` 가 아닐 때만 노출. `order_id` 가 없는 일반 대화방은 항상 노출
- 정렬: 주문 채팅 우선 → `last_message_at` (없으면 `created_at`) DESC
- 클릭 → `router.push(/{role}/chat?room_id={id})` + `onNavigate?.()` 로 부모 모달 닫기
- 주문 요약 라벨: `order.product_summary` 우선 (백엔드가 채워줌). 미제공 시 `items[0].product_name + qty + 외 N건` 폴백. 주문 정보가 아직 로드되기 전엔 "주문 정보 불러오는 중..." 표시

#### 빈 상태
"이 거래처와 진행 중인 채팅이 없어요. 새 주문이 들어오면 자동으로 채팅방이 열려요." — 점선 박스(`border-dashed`) + 회색 톤. 사용자가 직접 채팅을 만들 동작은 헤더의 "채팅 시작" 빠른액션이 이미 담당하므로 빈 상태에 별도 CTA 두지 않음.

#### PartnerDetailModal 통합
거래 통계 섹션과 정기배송 섹션 사이에 신규 `<section>` 으로 삽입. `MessageCircle` 아이콘 + "진행 중 채팅" 헤더. `isPendingOutgoing` 일 때는 채팅 액션 자체가 잠겨있으므로 섹션도 숨김 (정기배송 섹션과 동일한 가드 패턴).

```tsx
{!isPendingOutgoing && (
  <section>
    <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-gray-700">
      <MessageCircle className="h-4 w-4" /> 진행 중 채팅
    </h3>
    <PartnerChatRooms
      partnerUserId={partner.partner_user_id}
      myRole={myRole}
      onNavigate={onClose}
    />
  </section>
)}
```

#### 카드 스타일 — 모바일 대응
`flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between` — 좁은 화면(<640px)에선 라벨/메시지 위에 메타(시각·바로가기) 가 쌓이고, sm 이상에선 좌우 2열 배치. 메시지 한 줄은 항상 `truncate`.

#### 상대 시각 헬퍼
`ChatRoomGroup.formatRelativeTime` 와 동일 시그니처 (`방금 전 / N분 전 / N시간 전 / N일 전 / M.D`). 두 컴포넌트가 별개 파일이라 시그니처/로직만 맞춤. 향후 `lib/date.ts` 로 끌어올려 통합 예정.

### 납품일 변경 요청·승인 채팅 카드 (검증됨, 2026-04-29)

backend 가 `delivery_date_change_history` 테이블 + 4개 엔드포인트 (`/orders/{id}/delivery-date-changes` GET/POST + `.../{change_id}/accept`, `.../{change_id}/reject`) 추가. 채팅에는 3개 신규 message_type 이 broadcast 된다:
- `DELIVERY_DATE_CHANGE` — 변경 요청 발송. metadata: `{change_id, proposed_delivery_date, from_role, notes, status, previous_delivery_date}`
- `DELIVERY_DATE_ACCEPTED` — 수락. metadata: `{change_id, accepted_delivery_date, from_role}`. 이 시점에 `orders.delivery_date` 가 업데이트되고 캘린더 동기화됨
- `DELIVERY_DATE_REJECTED` — 거절. metadata: `{change_id, proposed_delivery_date, from_role}`

상태 가드: `QUOTE_REQUESTED`/`NEGOTIATING`/`CONFIRMED` 만 변경 요청 가능. `PREPARING` 이상은 백엔드 422.

#### MessageBubble 분기 추가 (components/chat/MessageBubble.tsx)
```tsx
case 'DELIVERY_DATE_CHANGE':
  return <DeliveryDateChangeCard message={message} metadata={metadata} isMine={isMine} />;
case 'DELIVERY_DATE_ACCEPTED':
  return <DeliveryDateAcceptedCard metadata={metadata} content={message.content} />;
case 'DELIVERY_DATE_REJECTED':
  return <DeliveryDateRejectedCard metadata={metadata} content={message.content} />;
```

`DeliveryDateChangeCard` 는 `CounterOfferCard` 패턴 그대로 (sky-300/sky-50 톤). 상대방 PENDING 일 때만 수락/거절 버튼 노출. Accept/Reject 시 `useAcceptDeliveryDateChange` / `useRejectDeliveryDateChange` 호출.

#### useDeliveryDateChanges (hooks/useDeliveryDateChanges.ts)
협상 훅과 동일 패턴. queryKey: `['orders', orderId, 'delivery-date-changes']`. **수락 mutation 만 `['calendar']` 도 invalidate** — 캘린더 화면이 같은 탭에 열려 있으면 새 납품일이 즉시 반영.

#### useChat.ts ORDER_RELATED_TYPES 확장
3개 신규 타입을 추가하고, `useMessagesWithWebSocket` useEffect 안에서:
- 모든 delivery date 메시지 → `['orders', orderId, 'delivery-date-changes']` invalidate
- `DELIVERY_DATE_ACCEPTED` 만 추가로 `['calendar']` invalidate

### 협상 의도 감지 — metadata.draft_negotiation + 본인 전용 WS push (US-2, 2026-05-04)

**핵심 보안 원칙: 자동 등록 절대 X, 발신자 본인에게만 카드 노출.**

평문 메시지 ("옥수수 50kg 7만원에 어때요?") 에서 가격 협상 의도를 감지해 본인이 [등록] 클릭 시 협상가 제시로 등록할 수 있도록 안내한다. 감지 결과는 `messages.metadata` JSONB 의 `draft_negotiation` 키에 별도 저장 — 기존 협상 흐름(`COUNTER_OFFER` 카드/`negotiations` 테이블) 과 완전 분리.

#### 흐름

```
POST /chat/rooms/{room_id}/messages
  → chat_service.send_message (메시지 INSERT, last_message UPDATE, NEW_MESSAGE notification)
  → 응답 즉시 반환 (201 + MessageResponse)
  → BackgroundTasks.add_task(process_message_for_negotiation)
        ├─ chat_room + (있으면) order_items + products 조회 → room_context
        ├─ OpenAI gpt-4o-mini structured output (response_format=json_object, temp=0)
        │    → {product_name, quantity, unit, unit_price, confidence}
        ├─ confidence < 0.7 → return (저장도 push도 안 함)
        ├─ messages.metadata['draft_negotiation'] = {...} UPDATE
        └─ ws_manager.send_private_message(sender_id, payload)
                payload: { type: "negotiation_draft_detected",
                           message_id, room_id, target_user_id: sender_id,
                           draft: {...} }
```

#### metadata.draft_negotiation 구조 (JSONB)

```json
{
  "draft_negotiation": {
    "product_name": "옥수수",   // string|null — 한국어 명사
    "quantity": 50,              // int|null — 양수
    "unit": "kg",                 // string|null — kg/box/piece/bag/개/포대 등
    "unit_price": 1400,           // int|null — KRW 정수, 양수
    "confidence": 0.9,            // float 0.0~1.0
    "detected_at": "2026-05-04T12:34:56.123456+00:00",
    "dismissed_at": null         // 사용자가 [무시] 클릭 시 NOW() 채움
  }
}
```

#### WS 이벤트 — `negotiation_draft_detected`

- `connection_manager.send_private_message(user_id, payload)` 사용 → 발신자 본인의 모든 활성 ws 에만 전송 (다중 탭 지원). broadcast 가 아니므로 채팅방 상대방은 절대 못 봄.
- 페이로드에 `target_user_id` 도 포함 (클라이언트 측 추가 가드용 — 정상 케이스에선 불필요하지만 디버깅/로깅 용이).
- 서버 재시작 시 in-memory 매핑이 사라지므로 즉시 push 가 도달 못 할 수 있음 → 그래서 metadata 저장도 같이 함 (페이지 새로고침/메시지 재로드 시 fallback).

#### 등록/무시 흐름

- [등록] 클릭 → 기존 `useSubmitCounterOfferViaChat` 또는 `POST /chat/rooms/{room_id}/counter-offer` 그대로 호출 (별도 신규 흐름 X). draft 의 `unit_price * quantity` 를 `proposed_total_amount` 로 변환.
- [무시] 클릭 → `PATCH /chat/messages/{message_id}/dismiss-draft-negotiation` (본인 메시지만, 멱등). 응답으로 갱신된 `draft_negotiation` 반환.
- 5분 timeout → **프론트가 시각적으로만 hide** (white-list `confidence>=0.7 && !dismissed_at && (now - detected_at) < 5min`). 백엔드는 timeout 처리 안 함.

#### 보안/중복 방지 가드 (검증됨)

1. `confidence >= 0.7` 미만은 metadata 저장도 WS push 도 안 함 → 잡담/안부 메시지로 false-positive 차단.
2. `_normalize_detection_result` 가 음수 quantity/unit_price/confidence 를 None/0 으로 강제.
3. 빈/4자 미만 메시지는 LLM 호출조차 하지 않음 (`_MIN_CONTENT_LENGTH = 4`).
4. `process_message_for_negotiation` 의 모든 예외는 try/except 로 흡수 — 채팅 흐름이 절대 막히지 않음.

#### messages.metadata JSONB 부분 업데이트 패턴

`negotiation_detection_service._save_draft_to_message_metadata` 는 fetch → merge → update 3-step 패턴. 기존 metadata 가 있으면 머지 보존(다른 키 덮어쓰지 않음), 없으면 새로 생성. SECURITY DEFINER RPC 가 없어서 `jsonb_set` 일괄 사용 불가하지만, 단건 mutation 이라 성능 영향 미미.

```typescript
if (msgType === 'DELIVERY_DATE_CHANGE' ||
    msgType === 'DELIVERY_DATE_ACCEPTED' ||
    msgType === 'DELIVERY_DATE_REJECTED') {
  if (orderId) {
    queryClient.invalidateQueries({
      queryKey: ['orders', orderId, 'delivery-date-changes']
    });
  }
  if (msgType === 'DELIVERY_DATE_ACCEPTED') {
    queryClient.invalidateQueries({ queryKey: ['calendar'] });
  }
}
```

#### ChatHeaderStatusControl — 헤더 우측 주문 상태 변경 드롭다운 (components/chat/ChatHeaderStatusControl.tsx)

채팅 헤더 우측 (AI 요약 버튼 옆)에 노출되는 컴포넌트. 채팅방에 연결된 주문이 있을 때
StatusBadge + ChevronDown 버튼으로 표시되고, 클릭 시 다음으로 전환 가능한 상태를 드롭다운으로 보여준다.

전환 규칙은 `seller/orders/page.tsx` 의 `sellerNextStatusMap` 과 정합성을 유지한다:
- **seller**: CONFIRMED → PREPARING → SHIPPING → COMPLETED (CONFIRMED 진입은 buyer 전용)
- **buyer**: QUOTE_REQUESTED → NEGOTIATING → CONFIRMED, SHIPPING → COMPLETED

```tsx
<ChatHeaderStatusControl
  orderId={linkedOrderId}      // selectedRoom?.order_id ?? null
  currentStatus={linkedOrderStatus}  // useOrder(linkedOrderId).data?.data?.status
  role="seller"  // 또는 "buyer"
/>
```

내부 동작:
- orderId 또는 currentStatus 가 null 이면 렌더 안 함 (주문 없는 채팅방은 깔끔)
- 다음 상태 후보가 비면 배지만 표시 (변경 불가 상태 = COMPLETED, CANCELLED 등)
- 외부 클릭 mousedown 으로 드롭다운 자동 닫힘 (PriceOfferPopover 와 동일 패턴)
- `useUpdateOrderStatus` 훅 사용 — `PATCH /orders/{id}/status` body `{status}` 호출
- 변경 성공 시 React Query 가 ['orders'], ['order', id] 자동 invalidate → 같은 페이지의 OrderContextBanner 도 함께 새로고침

채팅 헤더 레이아웃 (양 페이지 공통):
```tsx
<div className="flex items-center justify-between border-b border-gray-200 px-4 py-3">
  <div className="flex items-center gap-2">{/* 뒤로가기 + 상대방 이름 */}</div>
  <div className="flex items-center gap-2">
    <ChatHeaderStatusControl orderId={...} currentStatus={...} role="..." />
    <button>AI 요약</button>
  </div>
</div>
```

#### 채팅 입력창 빠른 액션 — DeliveryDatePopover (components/chat/DeliveryDatePopover.tsx)
`PriceOfferPopover` 패턴 복제 (sky 톤). `room.order_id` 가 있고 `orderStatus` 가 변경 가능 상태일 때만 활성. seller/buyer chat page 둘 다 입력창의 `<PriceOfferPopover />` **바로 우측**에 배치:
```tsx
<PriceOfferPopover roomId={selectedRoomId} orderId={linkedOrderId} currentTotal={linkedOrderTotal} />
<DeliveryDatePopover roomId={selectedRoomId} orderId={linkedOrderId}
  orderStatus={linkedOrderStatus} currentDeliveryDate={linkedOrderDeliveryDate} />
<input ... />
```

채팅 페이지에서 `useOrder(linkedOrderId)` 응답에서 `total_amount` / `status` / `delivery_date` 모두 추출해 두 popover 에 분배.

---

### AI 답장 초안 — POST /chat/draft (검증됨, 2026-05-03)

채팅방 입력창의 슬래시 명령(`/초안 ...`) 으로 호출하는 AI 답장 초안 엔드포인트. 채팅 메시지 테이블에 저장하지 않고 초안 텍스트만 반환 — 사용자가 검토·수정 후 일반 메시지로 직접 발송한다.

#### 엔드포인트 명세
- 메소드: `POST /api/v1/chat/draft`
- 인증: 본인 채팅방 참여자(seller/buyer) 검증 — 다른 사용자가 호출하면 403
- Body: `{ "room_id": UUID, "instruction": str }` (instruction min_length=1, max_length=500)
- 응답: `{ "data": { "draft": str } }`
- 에러: 채팅방 없음 404, 권한 없음 403, OpenAI 실패 502, 빈 초안 502

#### 구조 결정 — chat_node 재사용 안 함

`chat_node` 는 `send_chat_message` 도구를 가진 채라 자칫 메시지가 실제 발송될 위험이 있다 (orchestrator.py 라인 1928 의 `'"success": true' in result_content` 단락회로 등). 그래서 별도 `services/draft_service.py` 단일 함수 `generate_chat_draft(user_id, room_id, instruction)` 로 분리한다 — 도구 호출 없는 단순 OpenAI 호출만 수행, 메시지 INSERT 경로 자체가 없어 안전.

#### 컨텍스트 빌드 흐름 (draft_service.generate_chat_draft)

1. `_fetch_chat_room(room_id)` — chat_rooms 단건 조회. 2026-05-06 부터 `chat_rooms.deleted_at` 존재. 권한 검증 진입 자체를 차단하려면 `.is_("deleted_at", None)` 필터를 추가해 취소된 방으로의 답장 초안 생성을 막는 것이 권장된다.
2. 권한 검증 — `user_id` 가 seller_id/buyer_id 둘 중 하나여야 함
3. 병렬 fetch (`asyncio.gather`):
   - `_fetch_user(my_id)` — 본인 이름/회사명/역할
   - `_fetch_user(counterpart_id)` — 상대방 정보
   - `_fetch_recent_messages(room_id, 20)` — `is_("deleted_at", None)` + `order(created_at, desc)` + `limit(20)` 후 메모리에서 reverse
   - `_fetch_order_summary(order_id)` — `room.order_id` 가 있을 때만 (없으면 즉시 None)
4. `_build_system_prompt` — 본인/상대 정보 + 주문 요약 + 최근 대화 평탄화 텍스트 합성
5. user prompt = "사용자가 보낼 답장 초안을 작성해 주세요\n[사용자 지시]\n{instruction}"
6. OpenAI `gpt-4o-mini`, `temperature=0.5`, `max_tokens=400`, 일반 응답 (스트리밍 X)
7. `_sanitize_draft` — 마크다운 별표 제거 + 메타 prefix("초안:", "답장:" 등) 제거 + 코드블록 펜스 제거

#### 시스템 프롬프트 톤 (chat_node 와 일관)

- 마크다운 별표(**), 리스트 기호(-, *, 1.) 절대 금지 — chat_node 와 동일 정책
- 메타 설명("아래는 초안입니다" 등) 금지
- 응답은 사용자가 그대로 복사해 보낼 답장 본문만
- 정중하지만 간결한 비즈니스 한국어, 1~3문장 기본
- 가격/수량/납기일 등 구체 수치 요구 시 컨텍스트(주문/대화)에서 가져와 정확히 반영

#### 주의사항 & 함정

- **chat_rooms.deleted_at 처리 (2026-05-06 갱신)** — 마이그레이션 `20260506000001_add_deleted_at_to_chat_rooms.sql` 로 컬럼 추가됨. 이전의 "필터 금지" 가이드는 무효. `_fetch_chat_room` / `list_rooms` / chat 도구 후보 검색 모두 `.is_("deleted_at", None)` 필터 적용 가능. 주문 취소(`order_service.cancel_order`) 시 연결된 chat_rooms 가 자동 soft-delete 된다.
- **order_id 가 None 인 일반 채팅방도 동작해야 함** — `asyncio.ensure_future(asyncio.sleep(0, result=None))` 로 placeholder Future 를 만들어 gather 시그니처 통일.
- **메시지 테이블 INSERT 절대 안 함** — 사용자가 검토 후 직접 발송하는 흐름이라 send_message 호출 금지. 향후 "초안 자동 발송" 기능을 추가하더라도 별도 엔드포인트로 분리할 것.
- **OpenAI 호출 실패 시 502 + type(e).__name__** — RTT 초과 / 네트워크 에러 / 환각으로 빈 텍스트 반환은 모두 502 로 통일하여 프론트에서 "AI 응답 실패" UX 단일화.

#### 프론트엔드 통합 — MessageInput 슬래시 명령 (검증됨, 2026-05-03)

채팅 입력창은 `frontend/components/chat/MessageInput.tsx` 단일 공유 컴포넌트로 추출되어 있다. seller/buyer 두 페이지 모두 이 컴포넌트를 사용한다.

```tsx
// seller/buyer chat page.tsx — 입력창 + 빠른 액션 popover
<MessageInput
  roomId={selectedRoomId}
  isConnected={isConnected}
  onSend={handleSend}                              // (content: string) => void
  leadingActions={                                 // 입력창 좌측 슬롯 — 기존 popover 유지
    <>
      <PriceOfferPopover {...} />
      <DeliveryDatePopover {...} />
    </>
  }
/>
```

**슬래시 명령 처리 흐름:**
1. 사용자가 `/초안 [지시]` 형식으로 입력 (예: `/초안 가격 협상해줘`)
2. Enter → 메시지 발송 분기 X, 대신 `useGenerateChatDraft` mutation 호출 (POST /chat/draft)
3. 입력창은 그대로 유지 (실패 시 instruction 재전송 가능)
4. 입력창 위 회색 박스에 로딩 → 응답 도착 시 초안 텍스트 표시
5. "사용" 버튼 클릭 → 입력창 textarea 에 초안 텍스트 채워짐 + 박스 dismiss → 사용자가 자유롭게 수정·발송
6. "닫기" 버튼 / 에러 시 → 박스만 dismiss, 입력창은 원본 그대로

**`/초안 ` 으로 시작하지 않는 일반 메시지**: 기존 발송 흐름 그대로 (`onSend(content)` 호출 → 부모의 `wsSendMessage`).

**가드 규칙:**
- `/초안 ` 뒤에 instruction 이 비어있으면 발송도 초안 호출도 안 함 (Enter 무시)
- `/` 로 시작하지만 `/초안 ` 패턴이 아니면 슬래시 후보로 간주 → 발송 차단 + hint 박스 노출 ("/초안 [지시] 형식으로 AI 답장 초안을 받을 수 있어요")
- 전송 버튼 활성 조건: 일반 메시지는 trim 비어있지 않고 WS 연결됨 / `/초안 ` 명령은 mutation pending 아닐 때만 활성 (WS 연결 무관 — REST API)

**시각 디자인:**
- `/초안 ` 명령 입력 중에는 input 테두리/배경이 보라색 톤 (`border-purple-300 bg-purple-50/50`), 전송 버튼도 보라색 + Sparkles 아이콘으로 일반 발송과 시각적으로 구분
- 초안 박스: `bg-gray-50 border-gray-200 rounded-lg`, 라벨 "AI 초안" + Sparkles 아이콘, "사용" 은 `bg-primary-600`, "닫기" 는 outline

**훅 (`useGenerateChatDraft`):**
```tsx
// frontend/hooks/useChat.ts
export function useGenerateChatDraft() {
  return useMutation({
    mutationFn: async ({ roomId, instruction }) => {
      const res = await api.post<SuccessResponse<{ draft: string }>>(
        '/chat/draft',
        { room_id: roomId, instruction }
      );
      return res.data?.draft ?? '';
    },
  });
}
```

성공 시 `draft` 가 빈 문자열이면 에러 처리로 분기 (백엔드 `_sanitize_draft` 가 모두 제거한 극단 케이스 대비).

---

## 작업 체크리스트

- [x] FastAPI chat 라우터 (rooms, messages CRUD)
- [x] SQLAlchemy ChatRoom, Message 모델
- [ ] Supabase Realtime publication 설정
- [x] useWebSocketChat 훅 (WS 연결, 재연결, 송수신)
- [x] useChat 훅 (useChatRooms, useMessagesWithWebSocket 등)
- [ ] ChatRoomList 컴포넌트
- [x] seller/buyer 채팅 페이지 (WebSocket 통합, 연결 인디케이터)
- [x] 읽음 처리 (채팅방 진입 시 자동)
- [x] 안읽은 메시지 수 뱃지
- [x] AI 요약 버튼 연동
- [x] AI 답장 초안 (POST /chat/draft) 백엔드

---

## 실전 발견 사항

### ChatRoom 타입 — 백엔드 ChatRoomResponse 와 1:1 동기화 (2026-05-05)

`frontend/types/chat.ts` 의 `ChatRoom` 인터페이스는 백엔드 `schemas/chat.py` 의 `ChatRoomResponse` 와 필드 단위로 정확히 일치해야 한다. 누락 시 TS 컴파일은 통과하지만 런타임에 `room.updated_at` 등을 참조하는 코드가 `undefined` 를 받는다.

**현재 필수 필드** (백엔드 기준):
```ts
id, order_id, seller_id, buyer_id,
last_message, last_message_at,
created_at, updated_at,                  // updated_at 누락 빈번 — 주의
partner_name, partner_company, unread_count,
order_number?, first_product_name?       // 2026-05-05 추가 (둘 다 optional)
```

**검증 패턴**: 백엔드 `ChatRoomResponse` 를 수정할 때마다 `frontend/types/chat.ts` 도 같이 본다. validator-agent 가 잡아주지만, 작업 시 항상 양쪽을 같이 열어 diff 비교가 가장 안전하다.

### ChatRoomResponse — 주문 식별 필드 (2026-05-05)

채팅방 목록 화면에서 "주문 채팅" 으로만 표시되어 어떤 주문/상품에 대한 채팅인지 구분이 안 되는 UX 문제 해결을 위해 `ChatRoomResponse` 에 두 필드 추가:
```python
order_number: Optional[str] = None         # orders.order_number (예: ORD-20260505-001)
first_product_name: Optional[str] = None   # 해당 주문의 첫 라인 상품명
```

**`chat_service.list_rooms` 의 채워넣기 로직 — N+1 회피 패턴**:
1. `room.order_id` 가 있는 방 목록 수집 (set)
2. `orders` 한 번에 IN 절로 조회 → `{id: order_number}` 맵 작성
3. `order_items` 한 번에 IN 절로 조회 + **`product:products(name, deleted_at)` FK 임베딩** + `order("created_at", desc=False)` — 첫 라인 추출용
4. 메모리에서 order_id 별 첫 라인의 product.name 만 픽업 (이미 ASC 정렬이라 `if oid not in first_item_map:` 체크로 충분)
5. soft-deleted 상품은 스킵 → 다음 라인이 채워짐

```python
items_result = await asyncio.to_thread(
    lambda: self.client.table("order_items")
    .select("order_id, created_at, product:products(name, deleted_at)")
    .in_("order_id", order_ids)
    .order("created_at", desc=False)
    .execute()
)
first_item_map: dict[str, str] = {}
for item in (items_result.data or []):
    oid = item.get("order_id")
    if not oid or oid in first_item_map:
        continue
    product = item.get("product") or {}
    if product.get("deleted_at"):
        continue
    name = product.get("name")
    if name:
        first_item_map[oid] = name
```

**핵심 함정**: `order_items` 테이블에는 `product_name` 컬럼이 없다 (SKILL_DB.md 의 schema 참조 — `product_id` FK 만 존재). 처음 작업 지시에 `select("order_id, product_name")` 같은 잘못된 컬럼이 들어있어도 그대로 적용하면 PostgREST 가 `column does not exist` 오류를 던진다. **반드시 마이그레이션 / SQLAlchemy 모델로 컬럼 존재 여부를 사전 확인**한 뒤 FK 임베딩 패턴(`product:products(name)`)으로 우회한다.

### 주문 취소 → 채팅방 cascade soft-delete (2026-05-06, 마이그레이션 20260506000001)

주문 취소 시 연결된 채팅방을 자동으로 정리해 활성 거래만 채팅 목록에 노출하기 위한 흐름.

**마이그레이션**: `chat_rooms` 에 `deleted_at TIMESTAMPTZ DEFAULT NULL` 컬럼 추가.

**호출 경로 (단일 진입점)**:
- `order_service.cancel_order(order_id, reason, user)` 한 곳에서만 처리.
- `respond_cancel_request(approve)` 는 내부에서 `cancel_order` 를 호출 → 자동 커버.
- 따라서 cancel_order 한 곳에 cascade soft-delete 로직 추가만으로 두 경로 모두 처리됨.

**cancel_order 내부 순서** (중요 — ORDER_CANCELLED 메시지 발송이 채팅방 soft-delete 보다 먼저):
1. orders.status = 'CANCELLED' UPDATE
2. `_sync_calendar_events_for_order` — 캘린더 일정 정리
3. `_emit_chat_event(message_type="ORDER_CANCELLED")` — 채팅에 시스템 메시지 발송 (사용자가 마지막 상태를 볼 수 있도록)
4. `chat_rooms` 조회 (`order_id == cancelled_order` AND `deleted_at IS NULL`) → 각각 `chat_service.delete_room(id)` 호출

**`chat_service.delete_room(room_id)`**:
```python
async def delete_room(self, room_id: UUID | str) -> None:
    deleted_at = datetime.now(timezone.utc).isoformat()
    await asyncio.to_thread(
        lambda: self.rooms.update({"deleted_at": deleted_at})
        .eq("id", str(room_id)).execute()
    )
```
- 멱등성: 이미 삭제된 row 도 timestamp 가 갱신될 뿐 동작 자체는 안전.
- 실패는 best-effort (try/except + print log) — 취소 트랜잭션 자체에 영향 없음.

**`list_rooms` 필터**: SELLER/BUYER 양쪽 분기 모두 `.is_("deleted_at", None)` 추가 → 취소된 방은 목록에서 즉시 사라짐.

**messages 보존**: 채팅방 soft-delete 시 messages 는 그대로 둔다 (이력 보존). 메시지 단건 직접 조회는 여전히 가능 — 단, list_messages 진입 자체가 채팅방 목록을 거치지 않으므로 별도 cascade 불필요.

**기존 채팅방 검색 패턴 영향**:
- `_resolve_chat_room_candidates` (LLM 도구) — 취소된 방을 제외하려면 `.is_("deleted_at", None)` 필터 추가 권장.
- `get_or_create_room` — 양 당사자가 같은 (seller_id, buyer_id, order_id) 조합으로 다시 채팅 시작하면 soft-deleted 방이 검색에 잡혀 그대로 반환될 수 있음. 새 방을 만들고 싶으면 `.is_("deleted_at", None)` 필터를 select 단에 추가해야 함 (현재는 아직 미적용 — 주문 취소 후 같은 order_id 에 대해 재채팅하는 케이스가 거의 없어 후속 과제로 분리).

`order_items` 는 `deleted_at` 컬럼이 없으므로 (SKILL_DB.md 의 "deleted_at 컬럼 없는 테이블에 필터 적용 금지" 함정 참조), 임베딩한 자식 테이블 `products` 의 `deleted_at` 만 명시적으로 검사한다.
