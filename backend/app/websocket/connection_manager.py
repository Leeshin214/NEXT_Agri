from fastapi import WebSocket


class ConnectionManager:
    """room_id별 WebSocket 연결 관리 + user_id 개별 전송 지원.

    동일 user_id가 여러 탭/디바이스로 접속할 수 있으므로 user → set[WebSocket] 매핑을 사용한다.
    send_private_message는 해당 user의 모든 활성 ws에 동일 메시지를 전송한다.
    """

    def __init__(self):
        # room_id -> list of active WebSocket connections
        self.active_connections: dict[str, list[WebSocket]] = {}
        # user_id -> set of active WebSockets (다중 탭 지원)
        self.active_user_connections: dict[str, set[WebSocket]] = {}

    async def connect(self, room_id: str, websocket: WebSocket, user_id: str) -> None:
        await websocket.accept()
        if room_id not in self.active_connections:
            self.active_connections[room_id] = []
        self.active_connections[room_id].append(websocket)
        # user → set 매핑에 add (다중 탭 허용)
        if user_id not in self.active_user_connections:
            self.active_user_connections[user_id] = set()
        self.active_user_connections[user_id].add(websocket)

    def disconnect(self, room_id: str, websocket: WebSocket, user_id: str | None = None) -> None:
        if room_id in self.active_connections:
            try:
                self.active_connections[room_id].remove(websocket)
            except ValueError:
                pass
            if not self.active_connections[room_id]:
                del self.active_connections[room_id]
        if user_id and user_id in self.active_user_connections:
            ws_set = self.active_user_connections[user_id]
            ws_set.discard(websocket)
            if not ws_set:
                del self.active_user_connections[user_id]

    async def broadcast(self, room_id: str, message: dict) -> None:
        """방의 모든 연결에 JSON 메시지 브로드캐스트. 끊긴 ws는 자동 정리."""
        connections = self.active_connections.get(room_id, [])
        dead: list[WebSocket] = []
        for connection in list(connections):
            try:
                await connection.send_json(message)
            except Exception as e:
                print(f"[WS broadcast] 전송 실패 (ws 정리): {type(e).__name__}: {e}")
                dead.append(connection)
        # 끊긴 ws 정리
        if dead and room_id in self.active_connections:
            for ws in dead:
                try:
                    self.active_connections[room_id].remove(ws)
                except ValueError:
                    pass
            if not self.active_connections[room_id]:
                del self.active_connections[room_id]

    async def send_private_message(self, user_id: str, message: dict) -> None:
        """특정 user_id에 매핑된 모든 활성 ws에 JSON 메시지 전송. 끊긴 ws는 자동 정리."""
        ws_set = self.active_user_connections.get(user_id)
        if not ws_set:
            return
        dead: list[WebSocket] = []
        for ws in list(ws_set):
            try:
                await ws.send_json(message)
            except Exception as e:
                print(f"[WS private] user={user_id} 전송 실패 (ws 정리): {type(e).__name__}: {e}")
                dead.append(ws)
        # 끊긴 ws 정리
        for ws in dead:
            ws_set.discard(ws)
        if not ws_set:
            self.active_user_connections.pop(user_id, None)


manager = ConnectionManager()
