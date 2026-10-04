"""Redis keys shared by the brain runtime (writer) and the gateway/admin (readers)."""
from __future__ import annotations

RUNTIME_HEARTBEAT_KEY = "brseai:v1:runtime:heartbeat"
RUNTIME_HEARTBEAT_INTERVAL_SECONDS = 10
RUNTIME_HEARTBEAT_TTL_SECONDS = 30

# Per-room live ops state, expires with the room keys.
ROOM_AI_STATUS_KEY = "room:{room_id}:ai_status"  # HASH speaker_id -> latest interpreter.status
ROOM_AI_EVENTS_KEY = "room:{room_id}:ai_events"  # LIST newest-last ops events (traces + errors)
ROOM_AI_EVENTS_LIMIT = 150


def room_ai_status_key(room_id: str) -> str:
    return ROOM_AI_STATUS_KEY.format(room_id=room_id)


def room_ai_events_key(room_id: str) -> str:
    return ROOM_AI_EVENTS_KEY.format(room_id=room_id)
