from fastapi import WebSocket


class ConnectionManager:
    """room_id별 WebSocket 연결 관리"""

    def __init__(self):
        # room_id -> list of active WebSocket connections
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, room_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        if room_id not in self.active_connections:
            self.active_connections[room_id] = []
        self.active_connections[room_id].append(websocket)

    def disconnect(self, room_id: str, websocket: WebSocket) -> None:
        if room_id in self.active_connections:
            self.active_connections[room_id].remove(websocket)
            if not self.active_connections[room_id]:
                del self.active_connections[room_id]

    async def broadcast(self, room_id: str, message: dict) -> None:
        """방의 모든 연결에 JSON 메시지 브로드캐스트"""
        connections = self.active_connections.get(room_id, [])
        for connection in list(connections):
            await connection.send_json(message)


manager = ConnectionManager()
