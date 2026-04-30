import asyncio
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, Optional
from fastapi import WebSocket
import logging

logger = logging.getLogger(__name__)


@dataclass
class _ConnectionEntry:
    websocket: WebSocket
    session_id: str
    last_seen_monotonic: float


DisconnectCallback = Callable[[str, str, str, str], Awaitable[None]]

class WSHub:
    def __init__(
        self,
        on_connection_lost: Optional[DisconnectCallback] = None,
        stale_timeout_seconds: int = 90,
    ):
        # room_id -> {participant_id -> _ConnectionEntry}
        self.active_connections: Dict[str, Dict[str, _ConnectionEntry]] = {}
        self.on_connection_lost = on_connection_lost
        self.stale_timeout_seconds = max(stale_timeout_seconds, 15)

    async def connect(self, room_id: str, participant_id: str, session_id: str, websocket: WebSocket):
        await websocket.accept()
        if room_id not in self.active_connections:
            self.active_connections[room_id] = {}
            
        # If the participant already has a connection, close the old one
        old_entry = self.active_connections[room_id].get(participant_id)
        if old_entry and old_entry.websocket != websocket:
            try:
                await old_entry.websocket.close(code=4000, reason="Replaced by new connection")
            except Exception as e:
                logger.error(f"Error closing old websocket for {participant_id}: {e}")
            self._remove_connection(
                room_id,
                participant_id,
                old_entry.websocket,
                reason="replaced",
                trigger_cleanup=False,
            )
                
        self.active_connections[room_id][participant_id] = _ConnectionEntry(
            websocket=websocket,
            session_id=session_id,
            last_seen_monotonic=time.monotonic(),
        )

    def touch(self, room_id: str, participant_id: str, websocket: WebSocket) -> bool:
        if room_id in self.active_connections:
            entry = self.active_connections[room_id].get(participant_id)
            if entry and entry.websocket == websocket:
                entry.last_seen_monotonic = time.monotonic()
                return True
        return False

    def disconnect(
        self,
        room_id: str,
        participant_id: str,
        websocket: WebSocket,
        *,
        reason: str,
        trigger_cleanup: bool = True,
    ):
        self._remove_connection(
            room_id,
            participant_id,
            websocket,
            reason=reason,
            trigger_cleanup=trigger_cleanup,
        )

    def _remove_connection(
        self,
        room_id: str,
        participant_id: str,
        websocket: WebSocket,
        *,
        reason: str,
        trigger_cleanup: bool,
    ) -> bool:
        if room_id not in self.active_connections:
            return False

        entry = self.active_connections[room_id].get(participant_id)
        if entry is None or entry.websocket != websocket:
            return False

        session_id = entry.session_id
        del self.active_connections[room_id][participant_id]
        if not self.active_connections[room_id]:
            del self.active_connections[room_id]

        if trigger_cleanup and self.on_connection_lost:
            asyncio.create_task(self.on_connection_lost(room_id, participant_id, session_id, reason))
        return True

    async def send_to_participant(self, room_id: str, participant_id: str, message: dict):
        if room_id in self.active_connections and participant_id in self.active_connections[room_id]:
            entry = self.active_connections[room_id][participant_id]
            ws = entry.websocket
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.error(f"Failed to send WS message to {participant_id}: {e}")
                self.disconnect(room_id, participant_id, ws, reason="send_failed", trigger_cleanup=True)

    async def broadcast_to_room(self, room_id: str, message: dict):
        if room_id in self.active_connections:
            for p_id, entry in list(self.active_connections[room_id].items()):
                ws = entry.websocket
                try:
                    await ws.send_json(message)
                except Exception as e:
                    logger.error(f"Failed to broadcast WS message to {p_id}: {e}")
                    self.disconnect(room_id, p_id, ws, reason="broadcast_failed", trigger_cleanup=True)

    async def close_stale_connections(self):
        if not self.active_connections:
            return

        now = time.monotonic()
        stale: list[tuple[str, str, _ConnectionEntry]] = []
        for room_id, participants in self.active_connections.items():
            for participant_id, entry in participants.items():
                if now - entry.last_seen_monotonic >= self.stale_timeout_seconds:
                    stale.append((room_id, participant_id, entry))

        for room_id, participant_id, entry in stale:
            try:
                await entry.websocket.close(code=4001, reason="Stale websocket timeout")
            except Exception:
                logger.debug("Failed to close stale websocket for %s in room %s", participant_id, room_id)
            self._remove_connection(
                room_id,
                participant_id,
                entry.websocket,
                reason="stale_timeout",
                trigger_cleanup=True,
            )
