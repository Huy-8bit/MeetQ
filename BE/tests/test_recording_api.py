"""HTTP: in-room recording control, meeting history access, presigned URLs, admin
archive/retention endpoints. Authorization is by stable user ID, never display name."""
import asyncio
from datetime import timedelta

import pytest

from server.service.archive.retention import as_utc, utcnow
from server.service.archive.setup import build_archive_services, install
from server.service.auth.cookies import ADMIN_COOKIE, USER_COOKIE
from server.service.auth.sessions import ADMIN_REALM, USER_REALM, SessionStore
from server.service.gateway.app_state import app_state
from tests.archive_fakes import FakeEgress, MemoryStorage
from tests.fake_mongo import FakeMongoDatabase


class _History:
    def __init__(self, db):
        self.db = db
        self.enabled = True

    async def get_meeting_summary(self, room_id, summary_type="final"):
        return await self.db["meeting_summaries"].find_one({"room_id": room_id, "summary_type": summary_type})


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def env(gateway_app, fake_settings, fake_redis):
    fake_settings.meeting_archive_bucket = "meetq-archive-test"
    fake_settings.user_auth_required = True
    fake_settings.auth_cookie_secure = False
    fake_settings.admin_username = "ops"
    fake_settings.admin_password = "ops-password"
    db = FakeMongoDatabase()
    db["system_settings"].docs.append({"_id": "archive_lifecycle", "managed_since": utcnow() - timedelta(days=30)})
    storage = MemoryStorage()
    egress = FakeEgress()
    egress.storage = storage
    services = build_archive_services(
        fake_settings, redis=fake_redis, mongo_db=db, store=app_state.room_store, storage=storage, provider=egress
    )
    install(services)
    app_state.room_history = _History(db)
    app_state.admin_context = None
    gateway_app.cookies.clear()

    def session(realm, payload):
        token, _ = _run(SessionStore(fake_redis).create(realm, payload, 3600))
        return token

    class Env:
        client = gateway_app
        settings = fake_settings
        redis = fake_redis

        def __init__(self):
            self.db, self.storage, self.egress, self.services = db, storage, egress, services

        def sign_in(self, user_id, name="Huy"):
            token = session(USER_REALM, {"user": {"id": user_id, "email": f"{user_id}@example.com", "name": name, "avatar_url": None}})
            gateway_app.cookies.set(USER_COOKIE, token)

        def admin(self):
            token = session(ADMIN_REALM, {"admin": {"id": "adm_1", "username": "ops", "display_name": "ops"}})
            gateway_app.cookies.set(ADMIN_COOKIE, token, path="/api/admin")

        def join(self, room_id, name, language):
            res = gateway_app.post(f"/api/rooms/{room_id}/join", json={"display_name": name, "language": language})
            assert res.status_code == 200, res.text
            return res.json()

    yield Env()
    gateway_app.cookies.clear()
    app_state.archive_repo = app_state.archive_storage = app_state.recording_service = None
    app_state.archive_service = app_state.archive_worker = None
    app_state.room_history = None
    fake_settings.meeting_archive_bucket = None
    fake_settings.admin_username = fake_settings.admin_password = None


def _room(env):
    env.sign_in("usr_huy")
    room_id = env.client.post("/api/rooms", json={"room_languages": ["vi", "ja"]}).json()["room"]["room_id"]
    huy = env.join(room_id, "Huy", "vi")
    return room_id, huy


def _auth(join):
    return {"Authorization": f"Bearer {join['room_token']['token']}"}


def test_participant_starts_recording_and_room_snapshot_shows_it(env):
    room_id, huy = _room(env)
    res = env.client.post(f"/api/rooms/{room_id}/recordings", headers=_auth(huy))
    assert res.status_code == 200, res.text
    rec = res.json()["recording"]
    assert rec["status"] == "recording" and rec["started_by"]["display_name"] == "Huy"
    # A second click returns the same recording.
    again = env.client.post(f"/api/rooms/{room_id}/recordings", headers=_auth(huy)).json()["recording"]
    assert again["recording_id"] == rec["recording_id"] and len(env.egress.start_calls) == 1
    # Late joiner / lobby: the room snapshot says the meeting is being recorded.
    snapshot = env.client.get(f"/api/rooms/{room_id}").json()["room"]
    assert snapshot["recording"]["status"] == "recording" and snapshot["recording_available"] is True
    current = env.client.get(f"/api/rooms/{room_id}/recordings/current", headers=_auth(huy)).json()
    assert current["recording"]["recording_id"] == rec["recording_id"]
    # Every participant hears about it in realtime.
    published = " ".join(str(message) for message in getattr(env.redis, "published", []))
    assert "recording.starting" in published and "recording.started" in published


def test_recording_requires_a_participant_and_a_signed_in_user(env):
    room_id, huy = _room(env)
    assert env.client.post(f"/api/rooms/{room_id}/recordings").status_code in (401, 403)  # no room token
    env.client.cookies.clear()
    res = env.client.post(f"/api/rooms/{room_id}/recordings", headers=_auth(huy))
    assert res.status_code == 401 and res.json()["error"]["code"] == "auth_required"


def test_stop_is_idempotent_over_http(env):
    room_id, huy = _room(env)
    rec = env.client.post(f"/api/rooms/{room_id}/recordings", headers=_auth(huy)).json()["recording"]
    url = f"/api/rooms/{room_id}/recordings/{rec['recording_id']}/stop"
    first = env.client.post(url, headers=_auth(huy)).json()["recording"]
    second = env.client.post(url, headers=_auth(huy)).json()["recording"]
    assert first["status"] == second["status"] == "processing"
    assert env.egress.stop_calls == ["EG_1"]


def test_provider_failure_returns_error_and_meeting_continues(env):
    room_id, huy = _room(env)
    env.egress.fail_start = True
    res = env.client.post(f"/api/rooms/{room_id}/recordings", headers=_auth(huy))
    assert res.status_code == 503 and res.json()["error"]["code"] == "recording_failed"
    assert env.client.get(f"/api/rooms/{room_id}").status_code == 200  # room unaffected


async def _ended_meeting(env, room_id, *, users, ended_ago=timedelta(minutes=10), recording=True):
    db = env.db
    ended = utcnow() - ended_ago
    await db["rooms"].insert_one(
        {
            "room_id": room_id, "room_languages": ["vi", "ja"], "created_at": (ended - timedelta(minutes=30)).isoformat(),
            "ended_at": ended.isoformat(), "ended_at_dt": ended,
            "status_summary": {"state": "empty", "terminal": True, "reason": "empty"},
        }
    )
    for index, user_id in enumerate(users):
        await db["room_participants"].insert_one(
            {"room_id": room_id, "participant_id": f"pt_{index}", "display_name": "Huy", "language": "vi", "kind": "human", "user_id": user_id}
        )
    await db["room_messages"].insert_one({"room_id": room_id, "kind": "source", "text": "Xin chào", "created_at": ended.isoformat()})
    await db["meeting_summaries"].insert_one({"room_id": room_id, "summary_type": "final", "status": "completed"})
    rec_id = None
    if recording:
        recordings = env.services["recordings"]
        state = await recordings.start(room_id, participant_id="pt_0", display_name="Huy", user_id=users[0])
        rec_id = state["recording_id"]
        await recordings.stop(room_id, rec_id, reason="room_ended")
        env.egress.complete(f"EG_{len(env.egress.start_calls)}")
        await recordings.reconcile_once()
    await env.services["archives"].finalize_ended_meetings()
    return rec_id


def test_participant_sees_meeting_history_and_others_do_not(env):
    rec_id = _run(_ended_meeting(env, "rm_hist01", users=["usr_huy"]))
    env.sign_in("usr_huy")
    listing = env.client.get("/api/meetings").json()
    assert [m["room_id"] for m in listing["items"]] == ["rm_hist01"]
    row = listing["items"][0]
    assert row["recording"]["status"] == "ready" and row["retention_days"] == 7 and row["expires_at"]
    detail = env.client.get("/api/meetings/rm_hist01").json()
    assert detail["recordings"][0]["recording_id"] == rec_id and detail["recordings"][0]["playable"]
    assert detail["participants"][0]["is_you"] is True
    assert env.client.get("/api/meetings/rm_hist01/messages?kind=transcript").json()["items"][0]["text"] == "Xin chào"

    # Same display name, different account: no access.
    env.sign_in("usr_other", name="Huy")
    assert env.client.get("/api/meetings").json()["items"] == []
    assert env.client.get("/api/meetings/rm_hist01").status_code == 404
    assert env.client.post(f"/api/recordings/{rec_id}/playback-url").status_code == 404


def test_presigned_urls_only_after_authorization(env):
    rec_id = _run(_ended_meeting(env, "rm_hist02", users=["usr_huy"]))
    env.client.cookies.clear()
    assert env.client.post(f"/api/recordings/{rec_id}/playback-url").status_code == 401
    assert env.storage.presigned == []
    env.sign_in("usr_huy")
    play = env.client.post(f"/api/recordings/{rec_id}/playback-url").json()
    download = env.client.post(f"/api/recordings/{rec_id}/download-url").json()
    assert play["url"].startswith("https://s3.test/") and play["expires_in"] == 600
    assert "dl=1" in download["url"]
    # Nothing permanent is stored: the recording record holds the S3 key, never a URL.
    stored = _run(env.db["meeting_recordings"].find_one({"_id": rec_id}))
    assert "http" not in str(stored)


def test_expired_and_deleted_archives_return_410(env):
    rec_id = _run(_ended_meeting(env, "rm_hist03", users=["usr_huy"]))
    env.sign_in("usr_huy")
    _run(env.services["repo"].update_archive("arc_hist03", {"expires_at": utcnow() - timedelta(minutes=1)}))
    res = env.client.post(f"/api/recordings/{rec_id}/playback-url")
    assert res.status_code == 410 and res.json()["error"]["code"] == "meeting_archive_expired"
    assert env.client.get("/api/meetings").json()["items"] == []
    _run(env.services["archives"].cleanup_expired())
    res = env.client.get("/api/meetings/rm_hist03")
    assert res.status_code == 410 and res.json()["error"]["code"] == "meeting_archive_deleted"


# ── Admin ──────────────────────────────────────────────────────────────────


def test_admin_lists_archives_and_changes_global_retention(env):
    _run(_ended_meeting(env, "rm_adm001", users=["usr_huy"]))
    _run(_ended_meeting(env, "rm_adm002", users=["usr_huy"], recording=False))
    assert env.client.get("/api/admin/recordings").status_code == 401  # admin only
    env.admin()
    listing = env.client.get("/api/admin/recordings").json()
    assert {row["room_id"] for row in listing["items"]} == {"rm_adm001", "rm_adm002"}
    assert listing["default_retention_days"] == 7
    ready = env.client.get("/api/admin/recordings?filter=ready").json()["items"]
    assert [row["room_id"] for row in ready] == ["rm_adm001"]
    none_row = next(r for r in listing["items"] if r["room_id"] == "rm_adm002")
    assert none_row["recording"]["status"] == "none" and none_row["status"] == "ready"

    assert env.client.patch("/api/admin/settings/retention", json={"default_retention_days": 0}).status_code == 422
    res = env.client.patch("/api/admin/settings/retention", json={"default_retention_days": 30})
    assert res.json()["default_retention_days"] == 30 and res.json()["updated_by"] == "ops"
    # Existing archives keep their expiry.
    assert env.client.get("/api/admin/archives/arc_adm001").json()["archive"]["retention_days"] == 7


def test_admin_retention_override_warns_before_immediate_expiry(env):
    _run(_ended_meeting(env, "rm_adm003", users=["usr_huy"]))
    # The meeting was archived when it ended, 5 days ago.
    repo = env.services["repo"]
    archive = _run(repo.update_archive("arc_adm003", {"ended_at": utcnow() - timedelta(days=5)}))
    _run(repo.set_retention(archive, None))
    env.admin()
    res = env.client.patch("/api/admin/archives/arc_adm003/retention", json={"retention_days": 30})
    archive = res.json()["archive"]
    assert archive["retention_days"] == 30 and archive["retention_source"] == "custom"
    risky = env.client.patch("/api/admin/archives/arc_adm003/retention", json={"retention_days": 3})
    assert risky.status_code == 409 and risky.json()["error"]["code"] == "retention_expires_immediately"
    back = env.client.patch("/api/admin/archives/arc_adm003/retention", json={"use_default": True}).json()["archive"]
    assert back["retention_days"] == 7 and back["retention_source"] == "default"
    confirmed = env.client.patch("/api/admin/archives/arc_adm003/retention", json={"retention_days": 3, "confirm_expire": True})
    assert confirmed.status_code == 200 and as_utc(confirmed.json()["archive"]["expires_at"]) < utcnow()


def test_admin_delete_now_requires_typed_confirmation(env):
    _run(_ended_meeting(env, "rm_adm004", users=["usr_huy"]))
    env.admin()
    detail = env.client.get("/api/admin/archives/arc_adm004").json()
    assert len(detail["recordings"]) == 1 and detail["storage_bytes"] > 0
    assert env.client.request("DELETE", "/api/admin/archives/arc_adm004", json={"confirm": "yes"}).status_code == 422
    res = env.client.request("DELETE", "/api/admin/archives/arc_adm004", json={"confirm": "DELETE"})
    assert res.status_code == 200 and res.json()["archive"]["status"] == "deleted"
    assert res.json()["archive"]["deletion_reason"] == "admin_deleted"
    assert not [key for key in env.storage.objects if "rm_adm004" in key]


def test_admin_cannot_start_recordings(env):
    env.admin()
    paths = [getattr(route, "path", "") for route in env.client.app.routes]
    assert not [p for p in paths if p.startswith("/api/admin") and "recordings" in p and p != "/api/admin/recordings"]
