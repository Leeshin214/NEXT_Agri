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

```typescript
const { data: roomsData, isLoading: roomsLoading, error: roomsError, refetch: refetchRooms } = useChatRooms();

// JSX
{roomsLoading ? (
  <div className="flex items-center justify-center p-8">
    <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary-600 border-t-transparent" />
  </div>
) : roomsError ? (
  <div className="p-4 text-sm text-red-500">
    채팅방을 불러오지 못했습니다.
    <button onClick={() => refetchRooms()} className="ml-2 text-primary-600 underline">다시 시도</button>
  </div>
) : rooms.length === 0 ? (
  <p className="p-4 text-sm text-gray-400">채팅방이 없습니다.</p>
) : (
  rooms.map(...)
)}
```

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
