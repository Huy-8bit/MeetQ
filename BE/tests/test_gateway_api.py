import pytest
from fastapi.testclient import TestClient

def test_health(gateway_app: TestClient):
    res = gateway_app.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    assert "X-Request-ID" in res.headers

@pytest.mark.asyncio
async def test_room_flow(gateway_app: TestClient):
    # 1. Create Room
    res = gateway_app.post("/api/rooms")
    assert res.status_code == 200
    data = res.json()
    room_id = data["room"]["room_id"]
    assert room_id.startswith("rm_")
    
    # 2. Join Room
    join_payload = {
        "display_name": "Test User",
        "language": "vi",
        "client": {
            "sdk": "web",
            "version": "1.0"
        }
    }
    res = gateway_app.post(f"/api/rooms/{room_id}/join", json=join_payload)
    assert res.status_code == 200
    join_data = res.json()
    
    assert join_data["participant"]["display_name"] == "Test User"
    assert "token" in join_data["room_token"]
    assert "url" in join_data["websocket"]
    assert "token" in join_data["livekit"]
    
    room_token = join_data["room_token"]["token"]
    
    # 3. Get Room Snapshot
    res = gateway_app.get(f"/api/rooms/{room_id}")
    assert res.status_code == 200
    snap_data = res.json()
    assert snap_data["room"]["state"] == "active"
    assert snap_data["room"]["participant_count"] == 1
    assert snap_data["participants"][0]["display_name"] == "Test User"

    # 4. Leave Room
    headers = {
        "Authorization": f"Bearer {room_token}"
    }
    res = gateway_app.delete(f"/api/rooms/{room_id}/leave", headers=headers)
    assert res.status_code == 204
    
    # Check it's empty
    res = gateway_app.get(f"/api/rooms/{room_id}")
    assert res.status_code == 200
    snap_data = res.json()
    assert snap_data["room"]["state"] == "empty"
    assert snap_data["room"]["participant_count"] == 0

def test_join_room_invalid_language(gateway_app: TestClient):
    # Create Room
    res = gateway_app.post("/api/rooms")
    room_id = res.json()["room"]["room_id"]
    
    # Join with invalid language
    join_payload = {
        "display_name": "Test User",
        "language": "fr" # not supported
    }
    res = gateway_app.post(f"/api/rooms/{room_id}/join", json=join_payload)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "invalid_language"


def test_create_one_language_room_disables_voice_relay(gateway_app: TestClient):
    res = gateway_app.post(
        "/api/rooms",
        json={"room_languages": ["vi"], "brse_output_mode": "voice_text"},
    )
    assert res.status_code == 200
    room = res.json()["room"]
    assert room["room_languages"] == ["vi"]
    assert room["meeting_languages"] == ["vi"]
    assert room["audio_routing"]["ai_audio_output_enabled"] is False
    assert room["audio_routing"]["route_strategy"] == "single_language_source_capture"


def test_create_two_language_room_preserves_voice_text(gateway_app: TestClient):
    res = gateway_app.post(
        "/api/rooms",
        json={"room_languages": ["vi", "en"], "brse_output_mode": "voice_text"},
    )
    assert res.status_code == 200
    room = res.json()["room"]
    assert room["room_languages"] == ["vi", "en"]
    assert room["brse_output_mode"] == "voice_text"
    assert room["audio_routing"]["ai_audio_output_enabled"] is True
    assert room["audio_routing"]["route_strategy"] == "two_language_relay"


def test_create_multi_language_room_downgrades_voice_to_text_only(gateway_app: TestClient):
    res = gateway_app.post(
        "/api/rooms",
        json={"room_languages": ["vi", "en", "ja"], "brse_output_mode": "voice_text"},
    )
    assert res.status_code == 200
    room = res.json()["room"]
    assert room["room_languages"] == ["vi", "en", "ja"]
    assert room["meeting_languages"] == ["vi", "en", "ja"]
    assert room["brse_output_mode"] == "text_only"
    assert room["audio_routing"]["requested_brse_output_mode"] == "voice_text"
    assert room["audio_routing"]["output_mode_downgrade_reason"] == "multi_language_text_only"
    assert room["audio_routing"]["ai_audio_output_enabled"] is False
    assert room["audio_routing"]["route_strategy"] == "multi_language_text_caption"


def test_join_language_must_belong_to_room_languages(gateway_app: TestClient):
    res = gateway_app.post("/api/rooms", json={"room_languages": ["vi", "en"]})
    room_id = res.json()["room"]["room_id"]

    res = gateway_app.post(
        f"/api/rooms/{room_id}/join",
        json={"display_name": "Test User", "language": "ja"},
    )
    assert res.status_code == 422
    body = res.json()
    assert body["error"]["code"] == "invalid_language"
    assert body["error"]["details"]["room_languages"] == ["vi", "en"]


def test_create_room_legacy_language_pair_payload(gateway_app: TestClient):
    res = gateway_app.post(
        "/api/rooms",
        json={"language_a": "vi", "language_b": "en"},
    )
    assert res.status_code == 200
    room = res.json()["room"]
    assert room["room_languages"] == ["vi", "en"]
    assert room["meeting_languages"] == ["vi", "en"]
