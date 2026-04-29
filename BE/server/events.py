import uuid
from datetime import datetime, timezone
from typing import Any, Dict

GATEWAY_CONTROL_CHANNEL = "gateway:control"
INTERPRETER_EVENTS_CHANNEL = "interpreter:events"

class EventType:
    ROOM_CREATED = "room.created"
    PARTICIPANT_JOINED = "participant.joined"
    PARTICIPANT_UPDATED = "participant.updated"
    PARTICIPANT_LEFT = "participant.left"
    
    TRANSCRIPT_PARTIAL = "transcript.partial"
    TRANSCRIPT_FINAL = "transcript.final"
    
    INTERPRETER_STATUS = "interpreter.status"
    INTERPRETER_ERROR = "interpreter.error"

    PARTICIPANT_MEDIA_CONNECTED = "participant.media_connected"
    PARTICIPANT_MEDIA_DISCONNECTED = "participant.media_disconnected"

def build_envelope(event_type: str, room_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": event_type,
        "event_id": f"evt_{uuid.uuid4().hex[:12]}",
        "room_id": room_id,
        "sent_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "payload": payload
    }
