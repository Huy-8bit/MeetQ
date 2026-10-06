"""Real host / co-host / participant roles: creation, reconnect, permission matrix,
moderation (mute, remove, lock, password) and realtime sync. Roles are resolved on the
server from the signed-in user's ID — never from the request, never from a name."""
import asyncio
import json

import pytest

from server.service.auth.cookies import USER_COOKIE
from server.service.auth.sessions import USER_REALM, SessionStore
from server.service.gateway.app_state import app_state
from server.service.gateway.room_permissions import (
    PERMISSION_DENIED_MESSAGE,
    Permission,
    capabilities,
    has_permission,
    outranks,
)

PASSWORD = "blue-river-42"


class FakeModerator:
    def __init__(self):
        self.muted = []
        self.removed = []

    async def mute_microphone(self, room_id, identity):
        self.muted.append((room_id, identity))
        return True

    async def remove_participant(self, room_id, identity):
        self.removed.append((room_id, identity))
        return True


@pytest.fixture
def env(gateway_app, fake_settings, fake_redis):
    fake_settings.user_auth_required = True
    fake_settings.auth_cookie_secure = False
    moderator = FakeModerator()
    app_state.room_service.moderator = moderator
    tokens = {}

    class Env:
        client = gateway_app
        redis = fake_redis

        def __init__(self):
            self.moderator = moderator

        def as_user(self, user_id):
            if user_id not in tokens:
                token, _ = asyncio.run(
                    SessionStore(fake_redis).create(
                        USER_REALM,
                        {"user": {"id": user_id, "email": f"{user_id}@example.com", "name": user_id, "avatar_url": None}},
                        3600,
                    )
                )
                tokens[user_id] = token
            gateway_app.cookies.set(USER_COOKIE, tokens[user_id])
            return self

        def create(self, user_id, **body):
            self.as_user(user_id)
            res = gateway_app.post("/api/rooms", json={"room_languages": ["vi", "ja"], **body})
            assert res.status_code == 200, res.text
            return res.json()["room"]["room_id"]

        def join(self, room_id, user_id, name, *, password=None, expect=200):
            self.as_user(user_id)
            body = {"display_name": name, "language": "vi"}
            if password:
                body["password"] = password
            res = gateway_app.post(f"/api/rooms/{room_id}/join", json=body)
            assert res.status_code == expect, res.text
            return res.json()

        def call(self, method, path, user_id, join, **kwargs):
            self.as_user(user_id)
            headers = {"Authorization": f"Bearer {join['room_token']['token']}"}
            return gateway_app.request(method, path, headers=headers, **kwargs)

        def events(self, event_type):
            found = []
            for _channel, message in fake_redis.published:
                envelope = json.loads(message)
                if envelope["type"] == event_type:
                    found.append(envelope["payload"])
            return found

    yield Env()
    gateway_app.cookies.clear()
    fake_settings.user_auth_required = False
    app_state.room_service.moderator = None


def _pid(join):
    return join["participant"]["participant_id"]


# ── Permission matrix (unit) ───────────────────────────────────────────────


def test_permission_matrix():
    assert all(capabilities("host").values())
    co = capabilities("co_host")
    assert co["can_manage_ai"] and co["can_manage_recording"] and co["can_mute_participant"] and co["can_remove_participant"]
    assert not co["can_manage_password"] and not co["can_assign_cohost"] and not co["can_lock_room"]
    assert not any(capabilities("participant").values())
    # Unknown roles from anywhere are treated as the lowest role.
    assert not has_permission("admin", Permission.MANAGE_AI)
    assert outranks("host", "co_host") and outranks("co_host", "participant")
    assert not outranks("co_host", "host") and not outranks("co_host", "co_host") and not outranks("participant", "participant")


# ── Host creation & reconnect ──────────────────────────────────────────────


def test_room_creator_is_host_even_if_someone_else_joins_first(env):
    room_id = env.create("usr_a")
    b = env.join(room_id, "usr_b", "Kenji")
    a = env.join(room_id, "usr_a", "Huy")
    assert a["participant"]["role"] == "host"
    assert b["participant"]["role"] == "participant"
    perms = env.call("GET", f"/api/rooms/{room_id}/permissions", "usr_a", a).json()
    assert perms["role"] == "host" and perms["permissions"]["can_manage_password"] is True
    snapshot = env.client.get(f"/api/rooms/{room_id}").json()
    roles = {p["display_name"]: p["role"] for p in snapshot["participants"] if not p["is_virtual"]}
    assert roles == {"Huy": "host", "Kenji": "participant"}
    assert snapshot["room"]["host_participant_id"] == _pid(a)


def test_host_role_survives_leave_and_rejoin(env):
    room_id = env.create("usr_a")
    a = env.join(room_id, "usr_a", "Huy")
    env.join(room_id, "usr_b", "Kenji")
    assert env.call("DELETE", f"/api/rooms/{room_id}/leave", "usr_a", a).status_code == 204
    # While the host is away nobody is promoted.
    assert env.client.get(f"/api/rooms/{room_id}").json()["room"]["host_participant_id"] is None
    again = env.join(room_id, "usr_a", "Huy")
    assert again["participant"]["role"] == "host"
    assert _pid(again) != _pid(a)  # new realtime session, same person, same role


def test_display_name_is_not_identity(env):
    room_id = env.create("usr_a")
    impostor = env.join(room_id, "usr_x", "Huy")  # same name as the host, different account
    assert impostor["participant"]["role"] == "participant"


# ── AI relay & mode ────────────────────────────────────────────────────────


def test_participant_cannot_toggle_ai_or_change_mode(env):
    room_id = env.create("usr_a")
    env.join(room_id, "usr_a", "Huy")
    b = env.join(room_id, "usr_b", "Kenji")
    res = env.call("POST", f"/api/rooms/{room_id}/brse/disable", "usr_b", b)
    assert res.status_code == 403
    assert res.json()["error"] == {"code": "permission_denied", "message": PERMISSION_DENIED_MESSAGE}
    res = env.call("PATCH", f"/api/rooms/{room_id}/relay-mode", "usr_b", b, json={"mode": "text_only"})
    assert res.status_code == 403
    room = env.client.get(f"/api/rooms/{room_id}").json()["room"]
    assert room["brse_enabled"] is True and room["brse_output_mode"] == "voice_text"


def test_host_and_cohost_control_ai(env):
    room_id = env.create("usr_a")
    a = env.join(room_id, "usr_a", "Huy")
    b = env.join(room_id, "usr_b", "Kenji")
    assert env.call("PATCH", f"/api/rooms/{room_id}/relay-mode", "usr_a", a, json={"mode": "text_only"}).status_code == 200
    res = env.call("PATCH", f"/api/rooms/{room_id}/participants/{_pid(b)}/role", "usr_a", a, json={"role": "co_host"})
    assert res.status_code == 200 and res.json()["role"] == "co_host"
    assert env.call("POST", f"/api/rooms/{room_id}/brse/disable", "usr_b", b).status_code == 200
    assert env.client.get(f"/api/rooms/{room_id}").json()["room"]["brse_enabled"] is False


# ── Roles ──────────────────────────────────────────────────────────────────


def test_assign_and_remove_cohost_syncs_realtime(env):
    room_id = env.create("usr_a")
    a = env.join(room_id, "usr_a", "Huy")
    b = env.join(room_id, "usr_b", "Kenji")
    env.call("PATCH", f"/api/rooms/{room_id}/participants/{_pid(b)}/role", "usr_a", a, json={"role": "co_host"})
    changed = env.events("participant.role_changed")[-1]
    assert changed["old_role"] == "participant" and changed["new_role"] == "co_host"
    assert changed["participant_id"] == _pid(b) and changed["changed_by"] == _pid(a)
    updated = [p for p in env.events("participant.updated") if p["participant_id"] == _pid(b)][-1]
    assert updated["role"] == "co_host"
    member = json.loads(env.redis.data[f"room:{room_id}:members"]["usr_b"])
    assert member["role"] == "co_host"
    perms = env.call("GET", f"/api/rooms/{room_id}/permissions", "usr_b", b).json()
    assert perms["role"] == "co_host" and perms["permissions"]["can_manage_recording"] is True

    env.call("PATCH", f"/api/rooms/{room_id}/participants/{_pid(b)}/role", "usr_a", a, json={"role": "participant"})
    assert env.call("GET", f"/api/rooms/{room_id}/permissions", "usr_b", b).json()["role"] == "participant"
    # The role belongs to the user: it comes back on rejoin.
    env.call("PATCH", f"/api/rooms/{room_id}/participants/{_pid(b)}/role", "usr_a", a, json={"role": "co_host"})
    env.call("DELETE", f"/api/rooms/{room_id}/leave", "usr_b", b)
    assert env.join(room_id, "usr_b", "Kenji")["participant"]["role"] == "co_host"


def test_cohost_cannot_touch_the_host_or_room_security(env):
    room_id = env.create("usr_a", access="password", password=PASSWORD)
    a = env.join(room_id, "usr_a", "Huy", password=PASSWORD)
    b = env.join(room_id, "usr_b", "Kenji", password=PASSWORD)
    c = env.join(room_id, "usr_c", "Tuan", password=PASSWORD)
    env.call("PATCH", f"/api/rooms/{room_id}/participants/{_pid(b)}/role", "usr_a", a, json={"role": "co_host"})
    forbidden = [
        ("PATCH", f"/api/rooms/{room_id}/participants/{_pid(a)}/role", {"json": {"role": "participant"}}),
        ("PATCH", f"/api/rooms/{room_id}/participants/{_pid(c)}/role", {"json": {"role": "co_host"}}),
        ("POST", f"/api/rooms/{room_id}/participants/{_pid(a)}/remove", {}),
        ("POST", f"/api/rooms/{room_id}/participants/{_pid(a)}/mute", {}),
        ("POST", f"/api/rooms/{room_id}/lock", {}),
        ("PATCH", f"/api/rooms/{room_id}/password", {"json": {"password": "new-secret-1"}}),
        ("DELETE", f"/api/rooms/{room_id}/password", {}),
    ]
    for method, path, kwargs in forbidden:
        res = env.call(method, path, "usr_b", b, **kwargs)
        assert res.status_code == 403, (method, path, res.text)
    # The host cannot demote themselves (no host transfer yet).
    res = env.call("PATCH", f"/api/rooms/{room_id}/participants/{_pid(a)}/role", "usr_a", a, json={"role": "co_host"})
    assert res.status_code == 422
    # A client-supplied role is not a thing: extra fields change nothing.
    res = env.call("POST", f"/api/rooms/{room_id}/lock", "usr_c", c, json={"actor_role": "host"})
    assert res.status_code == 403


def test_room_token_must_belong_to_signed_in_user(env):
    room_id = env.create("usr_a")
    a = env.join(room_id, "usr_a", "Huy")
    env.join(room_id, "usr_b", "Kenji")
    # Someone signed in as usr_b presenting the host's room token is refused.
    assert env.call("POST", f"/api/rooms/{room_id}/lock", "usr_b", a).status_code == 403


# ── Mute ───────────────────────────────────────────────────────────────────


def test_host_mutes_participant_on_the_sfu_and_notifies(env):
    room_id = env.create("usr_a")
    a = env.join(room_id, "usr_a", "Huy")
    b = env.join(room_id, "usr_b", "Kenji")
    c = env.join(room_id, "usr_c", "Tuan")
    assert env.call("POST", f"/api/rooms/{room_id}/participants/{_pid(b)}/mute", "usr_c", c).status_code == 403
    res = env.call("POST", f"/api/rooms/{room_id}/participants/{_pid(b)}/mute", "usr_a", a)
    assert res.status_code == 200 and res.json()["provider_muted"] is True
    assert env.moderator.muted == [(room_id, _pid(b))]
    event = env.events("moderation.participant_muted")[-1]
    assert event["participant_id"] == _pid(b) and event["muted_by_host"] is True and event["muted_by"] == "Huy"
    target = [p for p in env.client.get(f"/api/rooms/{room_id}").json()["participants"] if p["participant_id"] == _pid(b)][0]
    assert target["muted_by_host"] is True
    # Legacy client route uses the same checks.
    res = env.call("POST", f"/api/rooms/{room_id}/moderation/mute", "usr_c", c, json={"target_participant_id": _pid(a)})
    assert res.status_code == 403


# ── Remove ─────────────────────────────────────────────────────────────────


def test_removed_user_is_disconnected_and_cannot_rejoin(env):
    room_id = env.create("usr_a")
    a = env.join(room_id, "usr_a", "Huy")
    b = env.join(room_id, "usr_b", "Kenji")
    env.call("PATCH", f"/api/rooms/{room_id}/participants/{_pid(b)}/role", "usr_a", a, json={"role": "co_host"})
    c = env.join(room_id, "usr_c", "Tuan")
    res = env.call("POST", f"/api/rooms/{room_id}/participants/{_pid(c)}/remove", "usr_b", b)  # co-host may remove
    assert res.status_code == 200 and res.json()["removed"] is True
    assert env.events("participant.removed")[-1]["participant_id"] == _pid(c)
    assert env.moderator.removed == [(room_id, _pid(c))]
    ids = [p["participant_id"] for p in env.client.get(f"/api/rooms/{room_id}").json()["participants"]]
    assert _pid(c) not in ids
    member = json.loads(env.redis.data[f"room:{room_id}:members"]["usr_c"])
    assert member["removed_at"] and member["removed_by_user_id"] == "usr_b"
    rejected = env.join(room_id, "usr_c", "Tuan", expect=403)
    assert rejected["error"] == {"code": "removed_from_room", "message": "You were removed from this meeting."}


# ── Lock ───────────────────────────────────────────────────────────────────


def test_locked_room_rejects_new_people_even_with_the_password(env):
    room_id = env.create("usr_a", access="password", password=PASSWORD)
    a = env.join(room_id, "usr_a", "Huy", password=PASSWORD)
    b = env.join(room_id, "usr_b", "Kenji", password=PASSWORD)
    assert env.call("POST", f"/api/rooms/{room_id}/lock", "usr_a", a).json()["locked"] is True
    assert env.events("room.lock_changed")[-1]["locked"] is True
    rejected = env.join(room_id, "usr_c", "Tuan", password=PASSWORD, expect=403)
    assert rejected["error"] == {"code": "room_locked", "message": "This meeting is locked by the host."}
    # People already in the meeting stay; someone who was already in can come back.
    inside = env.call("GET", f"/api/rooms/{room_id}", "usr_a", a).json()["participants"]
    assert _pid(b) in [p["participant_id"] for p in inside]
    env.call("DELETE", f"/api/rooms/{room_id}/leave", "usr_b", b)
    env.join(room_id, "usr_b", "Kenji", password=PASSWORD)
    assert env.call("POST", f"/api/rooms/{room_id}/unlock", "usr_a", a).json()["locked"] is False
    env.join(room_id, "usr_c", "Tuan", password=PASSWORD)


# ── Password ───────────────────────────────────────────────────────────────


def test_only_host_manages_password_and_it_is_never_returned(env):
    room_id = env.create("usr_a")
    a = env.join(room_id, "usr_a", "Huy")
    b = env.join(room_id, "usr_b", "Kenji")
    assert env.call("PATCH", f"/api/rooms/{room_id}/password", "usr_b", b, json={"password": "new-secret-1"}).status_code == 403
    res = env.call("PATCH", f"/api/rooms/{room_id}/password", "usr_a", a, json={"password": "new-secret-1"})
    assert res.status_code == 200 and res.json()["password_required"] is True
    assert "new-secret-1" not in res.text
    assert "new-secret-1" not in json.dumps(env.redis.data, default=str)
    assert "new-secret-1" not in json.dumps(env.redis.published, default=str)
    assert env.events("room.access_updated")[-1]["password_required"] is True
    env.join(room_id, "usr_c", "Tuan", password="wrong-pass", expect=403)
    env.join(room_id, "usr_c", "Tuan", password="new-secret-1")
    assert env.call("PATCH", f"/api/rooms/{room_id}/password", "usr_a", a, json={"password": "short"}).status_code == 422
    res = env.call("DELETE", f"/api/rooms/{room_id}/password", "usr_a", a)
    assert res.status_code == 200 and res.json()["password_required"] is False
    env.join(room_id, "usr_d", "Lan")


# ── Without sign-in (local tests) ──────────────────────────────────────────


def test_open_mode_keeps_legacy_ai_control_but_no_identity_actions(gateway_app, fake_settings):
    fake_settings.user_auth_required = False
    room_id = gateway_app.post("/api/rooms", json={"room_languages": ["vi", "ja"]}).json()["room"]["room_id"]
    join = gateway_app.post(f"/api/rooms/{room_id}/join", json={"display_name": "Mai", "language": "vi"}).json()
    other = gateway_app.post(f"/api/rooms/{room_id}/join", json={"display_name": "Lan", "language": "vi"}).json()
    headers = {"Authorization": f"Bearer {join['room_token']['token']}"}
    assert gateway_app.post(f"/api/rooms/{room_id}/brse/disable", headers=headers).status_code == 200
    assert gateway_app.post(f"/api/rooms/{room_id}/lock", headers=headers).status_code == 403
    res = gateway_app.post(f"/api/rooms/{room_id}/participants/{_pid(other)}/remove", headers=headers)
    assert res.status_code == 403
    perms = gateway_app.get(f"/api/rooms/{room_id}/permissions", headers=headers).json()
    assert perms["enforced"] is False and perms["permissions"]["can_manage_ai"] is True


def test_rooms_running_before_roles_keep_open_ai_until_they_end(env):
    room_id = env.create("usr_a")
    # Simulate a room created by the previous release: no recorded host, no roles flag.
    meta_key = f"room:{room_id}:meta"
    meta = json.loads(env.redis.data[meta_key])
    meta["roles_enabled"] = False
    env.redis.data[meta_key] = json.dumps(meta)
    env.redis.data.pop(f"room:{room_id}:members", None)
    b = env.join(room_id, "usr_b", "Kenji")
    assert b["participant"]["role"] == "participant"
    assert env.call("POST", f"/api/rooms/{room_id}/brse/disable", "usr_b", b).status_code == 200
    # Nobody is promoted, so identity actions stay unavailable in that room.
    assert env.call("POST", f"/api/rooms/{room_id}/lock", "usr_b", b).status_code == 403
    perms = env.call("GET", f"/api/rooms/{room_id}/permissions", "usr_b", b).json()
    assert perms["enforced"] is False


def test_removed_users_old_room_token_no_longer_reads_the_meeting(env):
    room_id = env.create("usr_a", access="password", password=PASSWORD)
    a = env.join(room_id, "usr_a", "Huy", password=PASSWORD)
    c = env.join(room_id, "usr_c", "Tuan", password=PASSWORD)
    env.call("POST", f"/api/rooms/{room_id}/participants/{_pid(c)}/remove", "usr_a", a)
    snapshot = env.call("GET", f"/api/rooms/{room_id}", "usr_c", c).json()
    assert [p for p in snapshot["participants"] if not p["is_virtual"]] == []  # lobby view only
    assert env.call("GET", f"/api/rooms/{room_id}/summary", "usr_c", c).status_code == 404
    assert env.call("POST", f"/api/rooms/{room_id}/brse/disable", "usr_c", c).status_code == 403
