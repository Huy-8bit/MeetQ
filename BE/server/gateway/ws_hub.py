from typing import Dict, Any
from fastapi import WebSocket
import logging

logger = logging.getLogger(__name__)

class WSHub:
    def __init__(self):
        # room_id -> {participant_id -> WebSocket}
        self.active_connections: Dict[str, Dict[str, WebSocket]] = {}

    async def connect(self, room_id: str, participant_id: str, websocket: WebSocket):
        await websocket.accept()
        if room_id not in self.active_connections:
            self.active_connections[room_id] = {}
            
        # If the participant already has a connection, close the old one
        old_ws = self.active_connections[room_id].get(participant_id)
        if old_ws and old_ws != websocket:
            try:
                await old_ws.close(code=4000, reason="Replaced by new connection")
            except Exception as e:
                logger.error(f"Error closing old websocket for {participant_id}: {e}")
                
        self.active_connections[room_id][participant_id] = websocket

    def disconnect(self, room_id: str, participant_id: str, websocket: WebSocket):
        if room_id in self.active_connections:
            if participant_id in self.active_connections[room_id]:
                # Only remove if it's the exact same websocket object
                if self.active_connections[room_id][participant_id] == websocket:
                    del self.active_connections[room_id][participant_id]
            
            if not self.active_connections[room_id]:
                del self.active_connections[room_id]

    async def send_to_participant(self, room_id: str, participant_id: str, message: dict):
        if room_id in self.active_connections and participant_id in self.active_connections[room_id]:
            ws = self.active_connections[room_id][participant_id]
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.error(f"Failed to send WS message to {participant_id}: {e}")
                self.disconnect(room_id, participant_id, ws)

    async def broadcast_to_room(self, room_id: str, message: dict):
        if room_id in self.active_connections:
            for p_id, ws in list(self.active_connections[room_id].items()):
                try:
                    await ws.send_json(message)
                except Exception as e:
                    logger.error(f"Failed to broadcast WS message to {p_id}: {e}")
                    self.disconnect(room_id, p_id, ws)
