import json
from datetime import datetime, timezone
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from server.gateway.app_state import app_state
from server.gateway.auth import verify_room_token, ExpiredTokenError, InvalidTokenError, TokenRoomMismatchError
from server.gateway.room_service import InvalidLanguageError, RoomNotFoundError, ParticipantNotFoundError
from server.events import EventType, build_envelope

router = APIRouter()

@router.websocket("/ws/rooms/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str, token: str = Query(None)):
    if not app_state.ws_hub or not app_state.room_service or not app_state.settings:
        await websocket.close(code=1011)
        return

    if not token:
        await websocket.close(code=4401, reason="Missing token")
        return

    try:
        claims = verify_room_token(token, app_state.settings.room_jwt_secret, room_id)
        participant_id = claims["participant_id"]
    except ExpiredTokenError:
        await websocket.close(code=4401, reason="Token expired")
        return
    except InvalidTokenError:
        await websocket.close(code=4401, reason="Invalid token")
        return
    except TokenRoomMismatchError:
        await websocket.close(code=4403, reason="Token room mismatch")
        return

    # Check if participant is still in the room
    try:
        snapshot = await app_state.room_service.get_room(room_id)
        # Verify participant is in the snapshot and not disconnected
        participant = next((p for p in snapshot.participants if p.participant_id == participant_id and p.status != "disconnected"), None)
        if not participant:
            await websocket.close(code=4403, reason="Participant not active in room")
            return
    except RoomNotFoundError:
        await websocket.close(code=4404, reason="Room not found")
        return

    await app_state.ws_hub.connect(room_id, participant_id, websocket)

    # Send initial snapshot
    # Add 'self' to snapshot payload
    personalized_snapshot = app_state.room_service.build_snapshot_data_for_participant(
        snapshot,
        participant_id,
    )
    snap_payload = {
        "self": {
            "participant_id": participant_id,
            "session_id": claims.get("session_id", ""),
            "display_name": participant.display_name,
            "language": participant.language
        },
        "room": snapshot.room.model_dump(),
        "participants": [p.model_dump() for p in personalized_snapshot.participants],
        "recent_transcripts": [t.model_dump() for t in personalized_snapshot.recent_transcripts]
    }
    
    await websocket.send_json(build_envelope("room.snapshot", room_id, snap_payload))

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                msg_type = msg.get("type")
                event_id = msg.get("event_id")
                payload = msg.get("payload", {})
                
                if msg_type == "ping":
                    pong_payload = {
                        "client_time": payload.get("client_time"),
                        "server_time": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                    }
                    await websocket.send_json({
                        "type": "pong",
                        "event_id": event_id,
                        "room_id": room_id,
                        "sent_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                        "payload": pong_payload
                    })
                
                elif msg_type == "set_language":
                    new_lang = payload.get("language")
                    try:
                        await app_state.room_service.set_language(room_id, participant_id, new_lang)
                        # `set_language` publishes event, Gateway consumer will fanout.
                    except InvalidLanguageError:
                        await websocket.send_json({
                            "type": "error",
                            "event_id": event_id,
                            "room_id": room_id,
                            "sent_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                            "payload": {
                                "code": "invalid_language",
                                "message": "language must be one of vi, en, ja"
                            }
                        })
                    except (RoomNotFoundError, ParticipantNotFoundError):
                        pass

            except json.JSONDecodeError:
                pass # Ignore malformed
    except WebSocketDisconnect:
        app_state.ws_hub.disconnect(room_id, participant_id, websocket)
