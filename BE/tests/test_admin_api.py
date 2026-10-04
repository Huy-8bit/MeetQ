import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from server.service.admin.auth import LoginRateLimiter
from server.service.auth.api import admin_failures
from server.service.gateway.app_state import app_state
from server.service.ops.recorder import AI_OPS_EVENTS_COLLECTION, OpsRecorder
from tests.fake_mongo import FakeMongoDatabase

ADMIN_USERNAME = "ops"
ADMIN_PASSWORD = "test-admin-password"


class _History:
    """Stands in for MongoRoomHistoryRepository: the admin only reads `.db`."""

    def __init__(self, db):
        self.db = db
        self.enabled = db is not None


def _reset_admin_limiter():
    for key in list(admin_failures._failures):
        admin_failures.reset(key)


@pytest.fixture
def mongo():
    return FakeMongoDatabase()


@pytest.fixture
def admin_client(gateway_app, fake_settings, fake_redis, mongo):
    fake_settings.admin_username = ADMIN_USERNAME
    fake_settings.admin_password = ADMIN_PASSWORD
    fake_settings.auth_cookie_secure = False  # TestClient talks plain http
    app_state.room_history = _History(mongo)
    app_state.admin_context = None
    app_state.ops_recorder = OpsRecorder(fake_redis, mongo, room_ttl_seconds=600)
    _reset_admin_limiter()
    gateway_app.cookies.clear()
    yield gateway_app
    gateway_app.cookies.clear()
    app_state.admin_context = None
    app_state.room_history = None
    app_state.ops_recorder = None
    fake_settings.admin_username = None
    fake_settings.admin_password = None


@pytest.fixture
def admin_headers(admin_client):
    """Signs in; the admin session travels as the meetq_admin_session cookie."""
    res = admin_client.post("/api/admin/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
    assert res.status_code == 200, res.text
    return {}


def _create_room(client, languages, **extra):
    res = client.post("/api/rooms", json={"room_languages": languages, **extra})
    assert res.status_code == 200, res.text
    return res.json()["room"]["room_id"]


def _join(client, room_id, name, language):
    res = client.post(f"/api/rooms/{room_id}/join", json={"display_name": name, "language": language})
    assert res.status_code == 200, res.text
    return res.json()


# ── Authorization ──────────────────────────────────────────────────────────

def test_admin_disabled_without_credentials(gateway_app, fake_settings):
    app_state.admin_context = None
    res = gateway_app.post("/api/admin/auth/login", json={"username": "ops", "password": "anything"})
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "admin_disabled"
    assert gateway_app.get("/api/admin/rooms").status_code == 503


def test_admin_login_and_protection(admin_client):
    assert admin_client.get("/api/admin/rooms").status_code == 401

    wrong = admin_client.post("/api/admin/auth/login", json={"username": ADMIN_USERNAME, "password": "nope"})
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "invalid_credentials"

    ok = admin_client.post("/api/admin/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
    assert ok.status_code == 200
    assert ok.json()["admin"]["username"] == ADMIN_USERNAME
    assert "token" not in ok.json()  # the session is only in the HttpOnly cookie
    assert admin_client.get("/api/admin/auth/me").status_code == 200
    assert admin_client.get("/api/admin/rooms").status_code == 200


def test_participant_room_token_cannot_access_admin(admin_client, create_room_jwt):
    room_token = create_room_jwt("rm_x", "pt_x", "ses_x")
    res = admin_client.get("/api/admin/rooms", headers={"Authorization": f"Bearer {room_token}"})
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "admin_auth_required"


def test_login_rate_limiter_blocks_after_repeated_failures():
    limiter = LoginRateLimiter(max_failures=3, window_seconds=60)
    for _ in range(3):
        limiter.record_failure("1.2.3.4", now=100.0)
    assert limiter.is_blocked("1.2.3.4", now=101.0)
    assert not limiter.is_blocked("1.2.3.4", now=200.0)


# ── Live rooms ─────────────────────────────────────────────────────────────

def test_live_rooms_list_filters_and_pagination(admin_client, admin_headers):
    vi_ja = _create_room(admin_client, ["vi", "ja"])
    _create_room(admin_client, ["en"])
    multi = _create_room(admin_client, ["vi", "ja", "en"])
    _join(admin_client, vi_ja, "Huy", "vi")

    res = admin_client.get("/api/admin/rooms", headers=admin_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 3
    by_id = {row["room_id"]: row for row in body["items"]}
    assert by_id[vi_ja]["status"] == "live"
    assert by_id[vi_ja]["participants_online"] == 1
    assert by_id[vi_ja]["ai_mode"] == "voice_text"
    assert by_id[multi]["ai_mode"] == "text_only"
    assert body["counts_by_status"]["empty"] == 2

    only_captions = admin_client.get("/api/admin/rooms?ai_mode=captions", headers=admin_headers).json()
    assert [row["ai_mode"] for row in only_captions["items"]] == ["captions"]

    japanese = admin_client.get("/api/admin/rooms?language=ja", headers=admin_headers).json()
    assert {row["room_id"] for row in japanese["items"]} == {vi_ja, multi}

    page = admin_client.get("/api/admin/rooms?page=2&page_size=2", headers=admin_headers).json()
    assert page["total"] == 3 and len(page["items"]) == 1

    assert admin_client.get("/api/admin/rooms?status=bogus", headers=admin_headers).status_code == 422


def test_live_room_detail_and_invalid_room(admin_client, admin_headers):
    assert admin_client.get("/api/admin/rooms/rm_missing", headers=admin_headers).status_code == 404

    room_id = _create_room(admin_client, ["vi", "ja"])
    _join(admin_client, room_id, "Huy", "vi")
    res = admin_client.get(f"/api/admin/rooms/{room_id}", headers=admin_headers)
    assert res.status_code == 200
    detail = res.json()
    assert detail["media_source"] == "unavailable"  # no LiveKit inspector in tests
    names = [participant["display_name"] for participant in detail["participants"]]
    assert "Huy" in names and "BRSE AI" in names
    assert detail["brse"]["enabled"] is True
    assert detail["brse"]["ai_mode"] == "voice_text"


def test_ops_events_feed_room_timeline_and_brse_state(admin_client, admin_headers, fake_redis, mongo):
    from server.events import EventType
    from server.service.gateway.event_consumer import _handle_interpreter_events

    room_id = _create_room(admin_client, ["vi", "ja"])
    speaker_id = _join(admin_client, room_id, "Huy", "vi")["participant"]["participant_id"]

    broadcasts = []

    class _Hub:
        async def broadcast_to_room(self, room, msg):
            broadcasts.append(msg["type"])

        async def send_to_participant(self, *args):
            pass

    app_state.ws_hub = _Hub()
    sent_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    async def feed():
        await fake_redis.rpush(
            f"room:{room_id}:transcripts",
            json.dumps({
                "transcript_id": "seg_1::source", "utterance_id": "seg_1", "kind": "source",
                "speaker_id": speaker_id, "speaker_display_name": "Huy", "src_lang": "vi",
                "source_text": "Mình deploy production tối nay.", "text": "Mình deploy production tối nay.",
                "created_at": sent_at,
            }),
        )
        await _handle_interpreter_events({
            "type": EventType.OPS_RELAY_TRACE, "room_id": room_id, "sent_at": sent_at,
            "payload": {
                "utterance_id": "seg_1", "speaker_id": speaker_id, "speaker_name": "Huy", "src_lang": "vi",
                "target_lang": "ja", "outcome": "relay_dropped", "reason": "stale_public_relay",
                "policy_decision": "publish", "source_accepted": True, "occurred_at": sent_at,
                "metrics": {"stt_ms": 620, "age_ms": 8720},
            },
        })
        await _handle_interpreter_events({
            "type": EventType.INTERPRETER_STATUS, "room_id": room_id, "sent_at": sent_at,
            "payload": {"speaker_id": speaker_id, "status": "translating", "target_language": "ja",
                        "relay_focus": {"active_speaker_id": speaker_id, "pending_relay_count": 2}},
        })
        await _handle_interpreter_events({
            "type": EventType.OPS_AI_ERROR, "room_id": room_id, "sent_at": sent_at,
            "payload": {"code": "realtime_auth_error", "message": "invalid_api_key sk-proj-123456789", "occurred_at": sent_at},
        })
        await asyncio.sleep(0)

    asyncio.run(feed())

    # Ops events are never fanned out to participants; status still is.
    assert broadcasts == [EventType.INTERPRETER_STATUS]
    stored = mongo[AI_OPS_EVENTS_COLLECTION].docs
    assert {doc["issue_code"] for doc in stored} == {"RELAY_TOO_LATE", "REALTIME_AUTH_FAILED"}
    assert all("sk-proj-123456789" not in str(doc) for doc in stored)

    timeline = admin_client.get(f"/api/admin/rooms/{room_id}/timeline", headers=admin_headers).json()
    assert timeline["source"] == "live"
    relay = next(item for item in timeline["items"] if item["event_type"] == "relay_trace")
    assert relay["source_text"] == "Mình deploy production tối nay."
    assert relay["stages"][-1]["note"] == "stale_public_relay"

    detail = admin_client.get(f"/api/admin/rooms/{room_id}", headers=admin_headers).json()
    assert detail["brse"]["state"] == "translating"
    assert detail["brse"]["queue_depth"] == 2
    assert detail["brse"]["current_speaker_name"] == "Huy"
    assert detail["brse"]["last_error"]["issue_code"] == "REALTIME_AUTH_FAILED"
    assert detail["room"]["status"] == "error"

    transcript = admin_client.get(f"/api/admin/rooms/{room_id}/transcript?kind=system", headers=admin_headers).json()
    assert transcript["items"] and transcript["items"][0]["kind"] == "system"


# ── History ────────────────────────────────────────────────────────────────

def _room_doc(room_id, created, **extra):
    doc = {
        "room_id": room_id,
        "created_at": created.isoformat().replace("+00:00", "Z"),
        "created_at_dt": created,
        "expires_at": (created + timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
        "expires_at_dt": created + timedelta(minutes=30),
        "room_languages": ["vi", "ja"],
        "brse_enabled": True,
        "brse_mode": "relay",
        "brse_output_mode": "voice_text",
        "participant_count_total": 2,
        "status_summary": {"state": "empty", "terminal": True},
        "duration_seconds": 900,
    }
    doc.update(extra)
    return doc


def test_meetings_history_filters_pagination_and_detail(admin_client, admin_headers, mongo):
    now = datetime.now(timezone.utc)
    rooms = mongo["rooms"]
    asyncio.run(rooms.insert_one(_room_doc("rm_old", now - timedelta(days=3), meeting_summaries={"final": {"status": "completed"}})))
    asyncio.run(rooms.insert_one(_room_doc("rm_text", now - timedelta(days=1), brse_output_mode="text_only", meeting_summaries={"final": {"status": "failed"}})))
    asyncio.run(rooms.insert_one(_room_doc("rm_en", now - timedelta(hours=2), room_languages=["en"])))
    asyncio.run(rooms.insert_one(_room_doc("rm_live", now - timedelta(minutes=5), status_summary={"terminal": False, "state": "active"})))
    asyncio.run(mongo["room_participants"].insert_one({"room_id": "rm_old", "display_name": "Kenji Tanaka", "is_virtual": False}))

    res = admin_client.get("/api/admin/meetings", headers=admin_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 4
    assert [row["room_id"] for row in body["items"]] == ["rm_live", "rm_en", "rm_text", "rm_old"]

    def ids(query):
        return [row["room_id"] for row in admin_client.get(f"/api/admin/meetings?{query}", headers=admin_headers).json()["items"]]

    assert ids("ai_mode=text_only") == ["rm_text"]
    assert ids("ai_mode=captions") == ["rm_en"]
    assert ids("summary_status=failed") == ["rm_text"]
    assert ids("status=live") == ["rm_live"]
    assert ids("q=kenji") == ["rm_old"]
    assert ids("language=en") == ["rm_en"]
    assert len(ids("page=2&page_size=3")) == 1

    assert admin_client.get("/api/admin/meetings/rm_nope", headers=admin_headers).status_code == 404
    detail = admin_client.get("/api/admin/meetings/rm_old", headers=admin_headers).json()
    assert detail["meeting"]["status"] == "ended"
    assert detail["summaries"]["final"]["status"] == "completed"


def test_meeting_relays_join_delivery_trace(admin_client, admin_headers, mongo):
    now = datetime.now(timezone.utc)
    asyncio.run(mongo["rooms"].insert_one(_room_doc("rm_r", now - timedelta(hours=1))))
    asyncio.run(mongo["room_messages"].insert_one({
        "room_id": "rm_r", "message_id": "seg_9::relay::ja", "kind": "relay", "utterance_id": "seg_9",
        "display_name": "Huy", "src_lang": "vi", "target_lang": "ja", "source_text": "xin chào",
        "brse_text": "こんにちは", "created_at": now.isoformat(), "created_at_dt": now,
    }))
    asyncio.run(mongo[AI_OPS_EVENTS_COLLECTION].insert_one({
        "room_id": "rm_r", "event_type": "relay_trace", "utterance_id": "seg_9", "outcome": "delivered",
        "metrics": {"total_ms": 1900}, "audio_requested": True, "audio_delivered": True,
    }))
    page = admin_client.get("/api/admin/meetings/rm_r/relays", headers=admin_headers).json()
    row = page["items"][0]
    assert row["translation"] == "こんにちは"
    assert row["delivery_state"] == "delivered"
    assert row["latency_ms"] == 1900
    assert row["voice_delivered"] is True


def test_issues_aggregate_ops_events_and_summary_failures(admin_client, admin_headers, mongo):
    now = datetime.now(timezone.utc)
    events = mongo[AI_OPS_EVENTS_COLLECTION]
    for index, room in enumerate(["rm_a", "rm_a", "rm_b"]):
        asyncio.run(events.insert_one({
            "event_id": f"e{index}", "event_type": "relay_trace", "room_id": room, "issue_code": "RELAY_TOO_LATE",
            "severity": "warning", "language_pair": "vi>ja", "outcome": "relay_dropped", "reason": "stale_public_relay",
            "occurred_at": now.isoformat(), "occurred_at_dt": now - timedelta(minutes=index),
        }))
    asyncio.run(events.insert_one({
        "event_id": "info", "event_type": "relay_trace", "room_id": "rm_a", "issue_code": "SOURCE_FILTERED",
        "severity": "info", "occurred_at_dt": now,
    }))
    asyncio.run(mongo["meeting_summaries"].insert_one({
        "room_id": "rm_c", "summary_type": "final", "status": "failed", "created_at": now.isoformat(), "created_at_dt": now,
    }))

    issues = admin_client.get("/api/admin/issues?window=24h", headers=admin_headers).json()["items"]
    by_code = {issue["code"]: issue for issue in issues}
    assert set(by_code) == {"RELAY_TOO_LATE", "SUMMARY_FAILED"}
    assert by_code["RELAY_TOO_LATE"]["occurrences"] == 3
    assert by_code["RELAY_TOO_LATE"]["affected_rooms"] == 2
    assert by_code["RELAY_TOO_LATE"]["top_language_pair"] == "vi>ja"
    assert issues[0]["code"] == "SUMMARY_FAILED"  # errors sort before warnings

    with_info = admin_client.get("/api/admin/issues?window=24h&include_info=true", headers=admin_headers).json()["items"]
    assert "SOURCE_FILTERED" in {issue["code"] for issue in with_info}

    detail = admin_client.get("/api/admin/issues/RELAY_TOO_LATE?page_size=2", headers=admin_headers).json()
    assert detail["occurrences"]["total"] == 3
    assert len(detail["occurrences"]["items"]) == 2
    assert admin_client.get("/api/admin/issues/NOT_A_CODE", headers=admin_headers).status_code == 404


def test_history_endpoints_report_unavailable_without_mongo(admin_client, admin_headers):
    app_state.admin_context = None
    app_state.room_history = _History(None)
    res = admin_client.get("/api/admin/meetings", headers=admin_headers)
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "history_unavailable"
    overview = admin_client.get("/api/admin/overview", headers=admin_headers).json()
    assert overview["history_available"] is False
    assert overview["kpis"]["meetings_today"]["available"] is False


def test_analytics_validates_range(admin_client, admin_headers):
    res = admin_client.get("/api/admin/analytics?from=2026-10-03T00:00:00Z&to=2026-10-01T00:00:00Z", headers=admin_headers)
    assert res.status_code == 422


def test_public_config_exposes_room_duration(gateway_app, fake_settings):
    res = gateway_app.get("/api/config")
    assert res.status_code == 200
    assert res.json()["room_meeting_duration_seconds"] == fake_settings.room_meeting_duration_seconds
