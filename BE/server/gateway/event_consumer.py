import json
import asyncio
import logging
from typing import Any, Dict
from redis.asyncio import Redis
from server.gateway.app_state import app_state
from server.events import GATEWAY_CONTROL_CHANNEL, INTERPRETER_EVENTS_CHANNEL, EventType
from server.models import TranscriptEvent

logger = logging.getLogger(__name__)


def _build_transcript_event(msg_data: Dict[str, Any]) -> TranscriptEvent:
    payload = msg_data.get("payload", {})
    speaker = payload.get("speaker", {}) or {}
    listener = payload.get("listener", {}) or {}
    src_lang = speaker.get("source_language") or speaker.get("language") or payload.get("src_lang") or "auto"
    target_lang = listener.get("target_language") or payload.get("tgt_lang")
    return TranscriptEvent(
        transcript_id=payload.get("transcript_id", ""),
        utterance_id=payload.get("utterance_id"),
        kind=payload.get("kind", "translated"),
        speaker_id=speaker.get("participant_id", ""),
        speaker_display_name=speaker.get("display_name", ""),
        speaker_language=speaker.get("language", src_lang),
        src_lang=src_lang,
        text=payload.get("text", ""),
        source_text=payload.get("source_text", ""),
        created_at=payload.get("created_at") or msg_data.get("sent_at", ""),
        is_final=payload.get("is_final", True),
        fallback_used=payload.get("fallback_used", False),
        listener_id=listener.get("participant_id"),
        target_lang=target_lang,
        translated_text=payload.get("translated_text"),
        audio_track_name=payload.get("audio_track_name"),
        audio_output=payload.get("audio_output"),
        speaker=speaker or None,
        listener=listener or None,
    )


def _is_transcript_visible_to_participant(
    transcript: TranscriptEvent,
    participant_id: str,
) -> bool:
    if transcript.kind == "source":
        return True
    return transcript.listener_id == participant_id

async def _handle_gateway_control(msg_data: dict):
    # These events just need to be broadcasted to the room (e.g., participant.joined)
    room_id = msg_data.get("room_id")
    if not room_id or not app_state.ws_hub:
        return
    await app_state.ws_hub.broadcast_to_room(room_id, msg_data)

async def _handle_interpreter_events(msg_data: dict):
    event_type = msg_data.get("type")
    room_id = msg_data.get("room_id")
    payload = msg_data.get("payload", {})
    
    if not room_id or not app_state.ws_hub or not app_state.room_store:
        return

    # Handle persistence
    if event_type == EventType.PARTICIPANT_MEDIA_CONNECTED:
        p_id = payload.get("participant_id")
        if p_id:
            await app_state.room_store.update_participant(room_id, p_id, {"media_connected": True})
            await app_state.ws_hub.broadcast_to_room(room_id, msg_data)
            
    elif event_type == EventType.PARTICIPANT_MEDIA_DISCONNECTED:
        p_id = payload.get("participant_id")
        if p_id:
            await app_state.room_store.update_participant(room_id, p_id, {"media_connected": False})
            await app_state.ws_hub.broadcast_to_room(room_id, msg_data)
            
    elif event_type == EventType.TRANSCRIPT_FINAL:
        transcript = _build_transcript_event(msg_data)
        try:
            await app_state.room_store.append_transcript(room_id, transcript)
        except Exception as e:
            logger.error(f"Failed to parse and save transcript: {e}")

        if transcript.kind == "source":
            await app_state.ws_hub.broadcast_to_room(room_id, msg_data)
        else:
            listener_id = transcript.listener_id
            if listener_id:
                await app_state.ws_hub.send_to_participant(room_id, listener_id, msg_data)

    elif event_type == EventType.TRANSCRIPT_PARTIAL:
        transcript = _build_transcript_event(msg_data)
        if transcript.kind == "source":
            await app_state.ws_hub.broadcast_to_room(room_id, msg_data)
        else:
            listener_id = transcript.listener_id
            if listener_id:
                await app_state.ws_hub.send_to_participant(room_id, listener_id, msg_data)

    elif event_type in (EventType.INTERPRETER_STATUS, EventType.INTERPRETER_ERROR):
        # We can broadcast these or send to specific targets.
        # Since status might be useful for everyone or specific languages, let's broadcast.
        await app_state.ws_hub.broadcast_to_room(room_id, msg_data)


def transcript_visible_to_participant(transcript: TranscriptEvent, participant_id: str) -> bool:
    return _is_transcript_visible_to_participant(transcript, participant_id)

async def start_event_consumer(redis: Redis):
    pubsub = redis.pubsub()
    await pubsub.subscribe(GATEWAY_CONTROL_CHANNEL, INTERPRETER_EVENTS_CHANNEL)
    logger.info("Event consumer started")
    
    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
                
            channel = message["channel"]
            data_str = message["data"]
            try:
                msg_data = json.loads(data_str)
            except json.JSONDecodeError:
                logger.error("Failed to decode message JSON")
                continue
                
            if channel == GATEWAY_CONTROL_CHANNEL:
                await _handle_gateway_control(msg_data)
            elif channel == INTERPRETER_EVENTS_CHANNEL:
                await _handle_interpreter_events(msg_data)
    except asyncio.CancelledError:
        logger.info("Event consumer cancelled")
    finally:
        await pubsub.unsubscribe()
