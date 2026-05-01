import json
from datetime import datetime, timezone
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from server.gateway.app_state import app_state
from server.gateway.auth import verify_room_token, ExpiredTokenError, InvalidTokenError, TokenRoomMismatchError
from server.gateway.room_service import (
    BrseToggleForbiddenError,
    InvalidChatMessageError,
    InvalidLanguageError,
    RoomNotFoundError,
    ParticipantNotFoundError,
)
from server.events import EventType, build_envelope

router = APIRouter()

@router.websocket("/ws/rooms/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str, token: str = Query(None)):
    if not app_state.ws_hub or not app_state.room_service or not app_state.room_store or not app_state.settings:
        await websocket.close(code=1011)
        return

    if not token:
        await websocket.close(code=4401, reason="Missing token")
        return

    try:
        claims = verify_room_token(token, app_state.settings.room_jwt_secret, room_id)
        participant_id = claims["participant_id"]
        session_id = claims.get("session_id")
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
        participant = next((p for p in snapshot.participants if p.participant_id == participant_id), None)
        if not participant:
            await websocket.close(code=4403, reason="Participant not active in room")
            return
        if participant.status == "disconnected":
            await websocket.close(code=4403, reason="Participant not active in room")
            return
        state_participant = await app_state.room_store.get_participant(room_id, participant_id)
        if not state_participant:
            await websocket.close(code=4403, reason="Participant not active in room")
            return
        if session_id and state_participant.session_id != session_id:
            await websocket.close(code=4403, reason="Session mismatch")
            return
    except RoomNotFoundError:
        await websocket.close(code=4404, reason="Room not found")
        return

    await app_state.ws_hub.connect(room_id, participant_id, state_participant.session_id, websocket)
    await app_state.room_service.touch_participant_presence(
        room_id,
        participant_id,
        state_participant.session_id,
        ws_connected=True,
        status="connected",
    )

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
        "recent_transcripts": [t.model_dump() for t in personalized_snapshot.recent_transcripts],
        "recent_messages": [m.model_dump() for m in personalized_snapshot.recent_messages],
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

                app_state.ws_hub.touch(room_id, participant_id, websocket)
                await app_state.room_service.touch_participant_presence(
                    room_id,
                    participant_id,
                    state_participant.session_id,
                )
                
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
                    except InvalidLanguageError as exc:
                        await websocket.send_json({
                            "type": "error",
                            "event_id": event_id,
                            "room_id": room_id,
                            "sent_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                            "payload": {
                                "code": "invalid_language",
                                "message": str(exc) or "language is not allowed for this room"
                            }
                        })
                    except (RoomNotFoundError, ParticipantNotFoundError):
                        pass

                elif msg_type == "chat.send":
                    try:
                        await app_state.room_service.send_chat_message(
                            room_id=room_id,
                            participant_id=participant_id,
                            session_id=state_participant.session_id,
                            text=payload.get("text") if isinstance(payload, dict) else None,
                            client_event_id=event_id,
                        )
                    except InvalidChatMessageError as exc:
                        await websocket.send_json({
                            "type": "error",
                            "event_id": event_id,
                            "room_id": room_id,
                            "sent_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                            "payload": {
                                "code": exc.code,
                                "message": str(exc) or "invalid chat message",
                            },
                        })
                    except RoomNotFoundError:
                        await websocket.send_json({
                            "type": "error",
                            "event_id": event_id,
                            "room_id": room_id,
                            "sent_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                            "payload": {
                                "code": "room_not_found",
                                "message": "room no longer exists",
                            },
                        })
                    except ParticipantNotFoundError:
                        await websocket.send_json({
                            "type": "error",
                            "event_id": event_id,
                            "room_id": room_id,
                            "sent_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                            "payload": {
                                "code": "participant_not_found",
                                "message": "participant no longer active",
                            },
                        })

                elif msg_type in {"room.brse.enable", "room.brse.disable"}:
                    try:
                        await app_state.room_service.set_brse_enabled(
                            room_id,
                            msg_type == "room.brse.enable",
                            actor_participant_id=participant_id,
                            session_id=state_participant.session_id,
                            reason="ws_enable" if msg_type == "room.brse.enable" else "ws_disable",
                        )
                    except RoomNotFoundError:
                        await websocket.send_json({
                            "type": "error",
                            "event_id": event_id,
                            "room_id": room_id,
                            "sent_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                            "payload": {
                                "code": "room_not_found",
                                "message": "room no longer exists",
                            },
                        })
                    except BrseToggleForbiddenError as exc:
                        await websocket.send_json({
                            "type": "error",
                            "event_id": event_id,
                            "room_id": room_id,
                            "sent_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                            "payload": {
                                "code": exc.code,
                                "message": str(exc),
                            },
                        })

                elif msg_type == "screen_share.start":
                    try:
                        ok = await app_state.room_service.start_screen_share(
                            room_id=room_id,
                            participant_id=participant_id,
                            session_id=state_participant.session_id,
                            track_sid=payload.get("track_sid"),
                            track_name=payload.get("track_name"),
                            source=payload.get("source", "screen_share"),
                        )
                        if not ok:
                            await websocket.send_json({
                                "type": "error",
                                "event_id": event_id,
                                "room_id": room_id,
                                "sent_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                                "payload": {
                                    "code": "session_mismatch",
                                    "message": "session is no longer valid",
                                },
                            })
                    except ParticipantNotFoundError:
                        await websocket.send_json({
                            "type": "error",
                            "event_id": event_id,
                            "room_id": room_id,
                            "sent_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                            "payload": {
                                "code": "participant_not_found",
                                "message": "participant no longer active",
                            },
                        })

                elif msg_type == "screen_share.stop":
                    try:
                        ok = await app_state.room_service.stop_screen_share(
                            room_id=room_id,
                            participant_id=participant_id,
                            session_id=state_participant.session_id,
                            reason="ws_stop",
                        )
                        if not ok:
                            await websocket.send_json({
                                "type": "error",
                                "event_id": event_id,
                                "room_id": room_id,
                                "sent_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                                "payload": {
                                    "code": "session_mismatch",
                                    "message": "session is no longer valid",
                                },
                            })
                    except ParticipantNotFoundError:
                        await websocket.send_json({
                            "type": "error",
                            "event_id": event_id,
                            "room_id": room_id,
                            "sent_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                            "payload": {
                                "code": "participant_not_found",
                                "message": "participant no longer active",
                            },
                        })

            except json.JSONDecodeError:
                pass # Ignore malformed
    except WebSocketDisconnect:
        pass
    finally:
        app_state.ws_hub.disconnect(
            room_id,
            participant_id,
            websocket,
            reason="client_disconnect",
            trigger_cleanup=True,
        )
