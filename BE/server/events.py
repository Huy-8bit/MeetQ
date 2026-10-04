import uuid
from datetime import datetime, timezone
from typing import Any, Dict

GATEWAY_CONTROL_CHANNEL = "gateway:control"
INTERPRETER_EVENTS_CHANNEL = "interpreter:events"

class EventType:
    ROOM_CREATED = "room.created"
    ROOM_EXPIRED = "room.expired"
    ROOM_BRSE_UPDATED = "room.brse_updated"
    # Room-level AI relay output mode (voice_text <-> text_only) changed in a live room.
    ROOM_RELAY_MODE_UPDATED = "room.relay_mode_updated"
    # Room-level recording state; every participant converges on the latest `version`.
    RECORDING_STARTING = "recording.starting"
    RECORDING_STARTED = "recording.started"
    RECORDING_STOPPING = "recording.stopping"
    RECORDING_STOPPED = "recording.stopped"
    RECORDING_PROCESSING = "recording.processing"
    RECORDING_READY = "recording.ready"
    RECORDING_FAILED = "recording.failed"
    PARTICIPANT_JOINED = "participant.joined"
    PARTICIPANT_UPDATED = "participant.updated"
    PARTICIPANT_LEFT = "participant.left"

    TRANSCRIPT_PARTIAL = "transcript.partial"
    TRANSCRIPT_FINAL = "transcript.final"

    INTERPRETER_STATUS = "interpreter.status"
    INTERPRETER_ERROR = "interpreter.error"

    PARTICIPANT_MEDIA_CONNECTED = "participant.media_connected"
    PARTICIPANT_MEDIA_DISCONNECTED = "participant.media_disconnected"
    SCREEN_SHARE_STARTED = "screen_share.started"
    SCREEN_SHARE_STOPPED = "screen_share.stopped"

    CHAT_MESSAGE = "chat.message"

    # Operations events (brain runtime -> gateway only; never fanned out to rooms)
    OPS_RELAY_TRACE = "ops.relay_trace"
    OPS_AI_ERROR = "ops.ai_error"

    # Mic test events (server -> client over test WS)
    MIC_TEST_STARTED = "mic_test.started"
    MIC_TEST_LEVEL = "mic_test.level"
    MIC_TEST_SILENCE = "mic_test.silence"
    MIC_TEST_STOPPED = "mic_test.stopped"
    MIC_TEST_ERROR = "mic_test.error"

    # Translation test events (server -> client over test WS)
    TRANSLATION_TEST_PARTIAL = "translation_test.partial"
    TRANSLATION_TEST_FINAL = "translation_test.final"
    TRANSLATION_TEST_ERROR = "translation_test.error"


def build_envelope(event_type: str, room_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": event_type,
        "event_id": f"evt_{uuid.uuid4().hex[:12]}",
        "room_id": room_id,
        "sent_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "payload": payload
    }


def build_test_event(event_type: str, session_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": event_type,
        "event_id": f"evt_{uuid.uuid4().hex[:12]}",
        "session_id": session_id,
        "sent_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "payload": payload,
    }
