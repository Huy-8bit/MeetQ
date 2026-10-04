"""Password-protected meeting rooms: create, lobby view, join verification, rate limit."""
import json
import logging

import pytest
from fastapi.testclient import TestClient

from server.service.gateway.app_state import app_state
from server.service.gateway.room_access import (
    hash_room_password,
    validate_room_password,
    verify_room_password,
)

PASSWORD = "blue-river-42"
JOIN = {"display_name": "Mai", "language": "vi", "client": {"sdk": "web", "version": "1"}}


def _create(client: TestClient, **body):
    return client.post("/api/rooms", json={"room_languages": ["vi", "ja"], **body})


def _protected_room(client: TestClient) -> str:
    res = _create(client, access="password", password=PASSWORD)
    assert res.status_code == 200, res.text
    return res.json()["room"]["room_id"]


def _all_redis_text(fake_redis) -> str:
    return json.dumps(fake_redis.data, default=str)


# ── Hashing ────────────────────────────────────────────────────────────────


def test_hash_is_argon2id_and_verifies():
    encoded = hash_room_password(PASSWORD)
    assert encoded.startswith("$argon2id$")
    assert PASSWORD not in encoded
    assert verify_room_password(PASSWORD, encoded)
    assert not verify_room_password("blue-river-43", encoded)
    assert not verify_room_password("", encoded)
    assert not verify_room_password(PASSWORD, "not-a-hash")
    assert hash_room_password(PASSWORD) != encoded  # salted


@pytest.mark.parametrize("password", ["12345", "x" * 129])
def test_password_length_rules(password):
    with pytest.raises(ValueError):
        validate_room_password(password)


@pytest.mark.parametrize("password", ["123456", "x" * 128, "パスワード123", "with spaces  "])
def test_password_accepts_any_characters(password):
    validate_room_password(password)


# ── Create ─────────────────────────────────────────────────────────────────


def test_public_room_by_default(gateway_app: TestClient):
    res = _create(gateway_app)
    assert res.status_code == 200
    assert res.json()["room"]["password_required"] is False


def test_create_protected_room_never_returns_or_stores_plaintext(gateway_app: TestClient, fake_redis):
    res = _create(gateway_app, access="password", password=PASSWORD)
    assert res.status_code == 200
    body = res.text
    room = res.json()["room"]
    assert room["password_required"] is True
    assert PASSWORD not in body and "password_hash" not in body and "argon2" not in body
    # Only the hash is stored, in its own key; the room meta carries just the flag.
    assert PASSWORD not in _all_redis_text(fake_redis)
    access = json.loads(fake_redis.data[f"room:{room['room_id']}:access"])
    assert access["password_hash"].startswith("$argon2id$")
    meta = json.loads(fake_redis.data[f"room:{room['room_id']}:meta"])
    assert meta["password_required"] is True and "password_hash" not in meta
    # Events published at creation carry no password material either.
    assert all(PASSWORD not in message and "argon2" not in message for _, message in fake_redis.published)


@pytest.mark.parametrize(
    "body",
    [
        {"access": "password"},
        {"access": "password", "password": "12345"},
        {"access": "password", "password": "x" * 129},
        {"access": "link", "password": PASSWORD},
    ],
)
def test_create_rejects_invalid_password_settings_without_echo(gateway_app: TestClient, body):
    res = _create(gateway_app, **body)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "invalid_room_password_setting"
    if body.get("password"):
        assert body["password"] not in res.text


# ── Lobby + join ───────────────────────────────────────────────────────────


def test_lobby_snapshot_hides_people_and_content(gateway_app: TestClient):
    room_id = _protected_room(gateway_app)
    join = gateway_app.post(f"/api/rooms/{room_id}/join", json={**JOIN, "password": PASSWORD})
    assert join.status_code == 200
    token = join.json()["room_token"]["token"]

    lobby = gateway_app.get(f"/api/rooms/{room_id}").json()
    assert lobby["room"]["password_required"] is True
    assert lobby["room"]["participant_count"] == 1
    assert all(p.get("is_virtual") for p in lobby["participants"])
    assert lobby["recent_transcripts"] == [] and lobby["recent_messages"] == []

    member = gateway_app.get(f"/api/rooms/{room_id}", headers={"Authorization": f"Bearer {token}"}).json()
    assert any(p["display_name"] == "Mai" for p in member["participants"])


def test_join_requires_password(gateway_app: TestClient):
    room_id = _protected_room(gateway_app)
    res = gateway_app.post(f"/api/rooms/{room_id}/join", json=JOIN)
    assert res.status_code == 403
    assert res.json()["error"] == {"code": "room_password_required", "message": "This meeting requires a password."}


def test_wrong_password_is_rejected_before_any_token(gateway_app: TestClient, caplog):
    room_id = _protected_room(gateway_app)
    with caplog.at_level(logging.DEBUG):
        res = gateway_app.post(f"/api/rooms/{room_id}/join", json={**JOIN, "password": "wrong-password"})
    assert res.status_code == 403
    body = res.json()
    assert body["error"]["code"] == "invalid_room_password"
    assert body["error"]["message"] == "Incorrect meeting password."
    assert "room_token" not in body and "livekit" not in body
    assert "wrong-password" not in caplog.text and PASSWORD not in caplog.text
    snapshot = gateway_app.get(f"/api/rooms/{room_id}").json()
    assert snapshot["room"]["participant_count"] == 0


def test_correct_password_joins(gateway_app: TestClient, caplog):
    room_id = _protected_room(gateway_app)
    with caplog.at_level(logging.DEBUG):
        res = gateway_app.post(f"/api/rooms/{room_id}/join", json={**JOIN, "password": PASSWORD})
    assert res.status_code == 200
    data = res.json()
    assert data["room_token"]["token"] and data["livekit"]["token"]
    assert PASSWORD not in res.text and PASSWORD not in caplog.text


def test_public_room_ignores_password_field(gateway_app: TestClient):
    room_id = _create(gateway_app).json()["room"]["room_id"]
    assert gateway_app.post(f"/api/rooms/{room_id}/join", json=JOIN).status_code == 200
    assert gateway_app.post(f"/api/rooms/{room_id}/join", json={**JOIN, "password": "anything"}).status_code == 200


def test_too_many_wrong_passwords_are_rate_limited(gateway_app: TestClient):
    room_id = _protected_room(gateway_app)
    limit = app_state.room_service.access.max_failures
    for _ in range(limit):
        res = gateway_app.post(f"/api/rooms/{room_id}/join", json={**JOIN, "password": "nope-nope"})
        assert res.status_code == 403
    blocked = gateway_app.post(f"/api/rooms/{room_id}/join", json={**JOIN, "password": PASSWORD})
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "room_password_rate_limited"
    assert int(blocked.headers["Retry-After"]) > 0
    # The limit is per room: another protected room is unaffected.
    other = _protected_room(gateway_app)
    assert gateway_app.post(f"/api/rooms/{other}/join", json={**JOIN, "password": PASSWORD}).status_code == 200


def test_join_validation_error_does_not_echo_password(gateway_app: TestClient):
    room_id = _protected_room(gateway_app)
    secret = "s3cret-" + "x" * 130
    res = gateway_app.post(f"/api/rooms/{room_id}/join", json={**JOIN, "password": secret})
    assert res.status_code == 422
    assert secret not in res.text


def test_protected_room_summary_needs_membership(gateway_app: TestClient):
    room_id = _protected_room(gateway_app)
    # No token, not a participant → hidden (no history store in this harness either way).
    res = gateway_app.get(f"/api/rooms/{room_id}/summary")
    assert res.status_code == 404
    token = gateway_app.post(f"/api/rooms/{room_id}/join", json={**JOIN, "password": PASSWORD}).json()["room_token"]["token"]
    res = gateway_app.get(f"/api/rooms/{room_id}/summary", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 404  # passes the access check; no summary stored yet
    assert res.json()["error"]["code"] == "meeting_summary_not_found"


def test_room_delete_removes_password_hash(gateway_app: TestClient, fake_redis):
    import asyncio

    room_id = _protected_room(gateway_app)
    assert f"room:{room_id}:access" in fake_redis.data
    asyncio.run(app_state.room_store.delete_room(room_id))
    assert f"room:{room_id}:access" not in fake_redis.data
