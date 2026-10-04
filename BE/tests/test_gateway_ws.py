import pytest
import json
from fastapi.testclient import TestClient
from server.service.gateway.auth import issue_room_token

@pytest.mark.asyncio
async def test_ws_connect_snapshot(gateway_app: TestClient, fake_settings):
    # Create room
    res = gateway_app.post("/api/rooms")
    room_id = res.json()["room"]["room_id"]
    
    # Join room to get participant and token
    # Default rooms are Vietnamese + Japanese; the join language must be one of them.
    join_res = gateway_app.post(f"/api/rooms/{room_id}/join", json={
        "display_name": "WS User",
        "language": "vi"
    })
    assert join_res.status_code == 200, join_res.text
    data = join_res.json()
    token = data["room_token"]["token"]
    participant_id = data["participant"]["participant_id"]
    
    with gateway_app.websocket_connect(f"/ws/rooms/{room_id}?token={token}") as websocket:
        # First message should be room.snapshot
        snapshot_msg = websocket.receive_json()
        assert snapshot_msg["type"] == "room.snapshot"
        assert snapshot_msg["room_id"] == room_id
        assert snapshot_msg["payload"]["self"]["participant_id"] == participant_id
        
        # Test ping
        websocket.send_json({
            "type": "ping",
            "event_id": "evt_ping",
            "payload": {
                "client_time": "test_time"
            }
        })
        pong_msg = websocket.receive_json()
        assert pong_msg["type"] == "pong"
        assert pong_msg["payload"]["client_time"] == "test_time"
        
        # Test set_language (we won't see broadcast here because GTW-006 is not yet implemented)
        # But we can verify it doesn't crash and we might see an error if invalid
        websocket.send_json({
            "type": "set_language",
            "event_id": "evt_lang",
            "payload": {
                "language": "ja"
            }
        })
        
        # Test invalid language
        websocket.send_json({
            "type": "set_language",
            "event_id": "evt_lang2",
            "payload": {
                "language": "fr"
            }
        })
        err_msg = websocket.receive_json()
        assert err_msg["type"] == "error"
        assert err_msg["payload"]["code"] == "invalid_language"
        
        # Test event consumer transcript.final fanout
        import asyncio
        from server.service.gateway.event_consumer import _handle_interpreter_events
        
        t_msg = {
            "type": "transcript.final",
            "room_id": room_id,
            "sent_at": "2026-04-29T14:57:00Z",
            "payload": {
                "transcript_id": "t_123",
                "speaker": {"participant_id": "pt_other", "display_name": "Other", "language": "ja", "source_language": "ja"},
                "listener": {"participant_id": participant_id, "target_language": "en"},
                "source_text": "Hello",
                "translated_text": "Hello in EN"
            }
        }
        
        # Simulate consumer receiving the event
        await _handle_interpreter_events(t_msg)
        
        ws_msg = websocket.receive_json()
        assert ws_msg["type"] == "transcript.final"
        assert ws_msg["payload"]["translated_text"] == "Hello in EN"

@pytest.mark.asyncio
async def test_ws_invalid_token(gateway_app: TestClient):
    from starlette.websockets import WebSocketDisconnect
    # Try connect with invalid token
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with gateway_app.websocket_connect(f"/ws/rooms/rm_123?token=invalid"):
            pass
    assert excinfo.value.code == 4401
