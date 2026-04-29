import json
import asyncio
import logging
from redis.asyncio import Redis
from server.gateway.app_state import app_state
from server.events import GATEWAY_CONTROL_CHANNEL, INTERPRETER_EVENTS_CHANNEL, EventType
from server.models import TranscriptEvent

logger = logging.getLogger(__name__)

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
        # Save to store
        try:
            t_event = TranscriptEvent(
                transcript_id=payload.get("transcript_id", ""),
                speaker_id=payload.get("speaker", {}).get("participant_id", ""),
                speaker_display_name=payload.get("speaker", {}).get("display_name", ""),
                src_lang=payload.get("speaker", {}).get("source_language", "auto"),
                source_text=payload.get("source_text", ""),
                created_at=msg_data.get("sent_at", "")
            )
            await app_state.room_store.append_transcript(room_id, t_event)
        except Exception as e:
            logger.error(f"Failed to parse and save transcript: {e}")
            
        # Fan-out to specific listener
        listener_id = payload.get("listener", {}).get("participant_id")
        if listener_id:
            await app_state.ws_hub.send_to_participant(room_id, listener_id, msg_data)
            
    elif event_type == EventType.TRANSCRIPT_PARTIAL:
        listener_id = payload.get("listener", {}).get("participant_id")
        if listener_id:
            await app_state.ws_hub.send_to_participant(room_id, listener_id, msg_data)
            
    elif event_type in (EventType.INTERPRETER_STATUS, EventType.INTERPRETER_ERROR):
        # We can broadcast these or send to specific targets.
        # Since status might be useful for everyone or specific languages, let's broadcast.
        await app_state.ws_hub.broadcast_to_room(room_id, msg_data)

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
