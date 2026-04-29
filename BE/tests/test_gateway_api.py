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
