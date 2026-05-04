import asyncio
import json
import logging
from typing import Any, Dict

from redis.asyncio import Redis

from server.events import EventType
from server.service.gateway.app_state import app_state
from server.service.gateway.room_service import ParticipantNotFoundError
from server.models import TranscriptEvent

logger = logging.getLogger(__name__)


def _build_transcript_event(msg_data: Dict[str, Any]) -> TranscriptEvent:
    payload = msg_data.get("payload", {})
    speaker = payload.get("speaker", {}) or {}
    original_speaker = payload.get("original_speaker", speaker) or {}
    brse_participant = payload.get("brse_participant") or {}
    listener = payload.get("listener", {}) or {}
    relay_target = payload.get("relay_target", {}) or {}

    src_lang = (
        original_speaker.get("source_language")
        or original_speaker.get("language")
        or speaker.get("source_language")
        or payload.get("src_lang")
        or "auto"
    )
    target_lang = (
        relay_target.get("target_language")
        or listener.get("target_language")
        or payload.get("tgt_lang")
    )

    return TranscriptEvent(
        transcript_id=payload.get("transcript_id", ""),
        utterance_id=payload.get("utterance_id"),
        kind=payload.get("kind", "relay"),
        speaker_id=original_speaker.get("participant_id", speaker.get("participant_id", "")),
        speaker_display_name=original_speaker.get("display_name", speaker.get("display_name", "")),
        speaker_language=original_speaker.get("language", src_lang),
        src_lang=src_lang,
        text=payload.get("text", ""),
        source_text=payload.get("source_text", ""),
        created_at=payload.get("created_at") or msg_data.get("sent_at", ""),
        is_final=payload.get("is_final", True),
        fallback_used=payload.get("fallback_used", False),
        listener_id=listener.get("participant_id"),
        target_lang=target_lang,
        translated_text=payload.get("translated_text"),
        brse_text=payload.get("brse_text"),
        audio_track_name=payload.get("audio_track_name"),
        audio_output=payload.get("audio_output"),
        relay_mode=payload.get("relay_mode"),
        relay_style=payload.get("relay_style"),
        speaker=speaker or None,
        original_speaker=original_speaker or None,
        listener=listener or None,
        brse_participant=brse_participant or None,
        relay_target=relay_target or None,
    )


def _is_transcript_visible_to_participant(
    transcript: TranscriptEvent,
    participant_id: str,
) -> bool:
    if transcript.kind in {"source", "relay"}:
        return True
    return transcript.listener_id == participant_id


async def _handle_gateway_control(msg_data: dict):
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

    snapshot = await app_state.room_store.get_room_snapshot(room_id)
    if snapshot is None or not snapshot.room.brse_enabled:
        return

    if event_type == EventType.PARTICIPANT_MEDIA_CONNECTED:
        p_id = payload.get("participant_id")
        if p_id:
            await app_state.room_store.update_participant(room_id, p_id, {"media_connected": True})
            await app_state.ws_hub.broadcast_to_room(room_id, msg_data)

    elif event_type == EventType.PARTICIPANT_MEDIA_DISCONNECTED:
        p_id = payload.get("participant_id")
        if p_id:
            await app_state.room_store.update_participant(room_id, p_id, {"media_connected": False})
            if app_state.room_service:
                try:
                    await app_state.room_service.stop_screen_share(
                        room_id=room_id,
                        participant_id=p_id,
                        session_id=None,
                        reason="media_disconnected",
                    )
                except ParticipantNotFoundError:
                    pass
            await app_state.ws_hub.broadcast_to_room(room_id, msg_data)

    elif event_type == EventType.TRANSCRIPT_FINAL:
        transcript = _build_transcript_event(msg_data)
        try:
            await app_state.room_store.append_transcript(room_id, transcript)
        except Exception as exc:
            logger.error("Failed to parse and save transcript: %s", exc)
        if app_state.room_history:
            app_state.room_history.schedule(
                lambda: app_state.room_history.persist_transcript(
                    room_id,
                    transcript,
                    room=snapshot.room,
                ),
                action="transcript_final",
                room_id=room_id,
            )

        if transcript.kind in {"source", "relay"}:
            await app_state.ws_hub.broadcast_to_room(room_id, msg_data)
        elif transcript.listener_id:
            await app_state.ws_hub.send_to_participant(room_id, transcript.listener_id, msg_data)

    elif event_type == EventType.TRANSCRIPT_PARTIAL:
        transcript = _build_transcript_event(msg_data)
        if transcript.kind in {"source", "relay"}:
            await app_state.ws_hub.broadcast_to_room(room_id, msg_data)
        elif transcript.listener_id:
            await app_state.ws_hub.send_to_participant(room_id, transcript.listener_id, msg_data)

    elif event_type in (EventType.INTERPRETER_STATUS, EventType.INTERPRETER_ERROR):
        await app_state.ws_hub.broadcast_to_room(room_id, msg_data)


def transcript_visible_to_participant(transcript: TranscriptEvent, participant_id: str) -> bool:
    return _is_transcript_visible_to_participant(transcript, participant_id)


async def start_event_consumer(redis: Redis):
    gateway_control_channel = "gateway:control"
    interpreter_events_channel = "interpreter:events"
    if app_state.settings:
        gateway_control_channel = app_state.settings.redis_channel_gateway_control
        interpreter_events_channel = app_state.settings.redis_channel_interpreter_events

    pubsub = redis.pubsub()
    await pubsub.subscribe(gateway_control_channel, interpreter_events_channel)
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

            if channel == gateway_control_channel:
                await _handle_gateway_control(msg_data)
            elif channel == interpreter_events_channel:
                await _handle_interpreter_events(msg_data)
    except asyncio.CancelledError:
        logger.info("Event consumer cancelled")
    finally:
        await pubsub.unsubscribe()
