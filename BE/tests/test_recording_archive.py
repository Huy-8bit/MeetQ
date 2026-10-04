"""Recording lifecycle, meeting archive and retention (service level, no AWS/LiveKit).

Covers: idle → starting → recording → stopping → processing → ready, idempotent and
concurrent start/stop, auto-stop at room end, provider failure, segments, archive
contents + manifest, legacy meetings, upload retry, retention snapshot/override,
expired cleanup (S3 + DB) and its idempotency.
"""
import asyncio
from datetime import timedelta

import pytest

from server.config import Settings
from server.events import EventType
from server.service.archive.archive_service import ArchiveService
from server.service.archive.egress import JOB_ACTIVE, JOB_FAILED, JOB_STARTING
from server.service.archive.recording_service import RecordingError, RecordingService, public_recording
from server.service.archive.repository import ArchiveRepository
from server.service.archive.retention import as_utc, utcnow
from tests.archive_fakes import FakeEgress, MemoryStorage
from tests.conftest import FakeRedis
from tests.fake_mongo import FakeMongoDatabase

ROOM = "rm_abc123"


class Harness:
    def __init__(self, settings: Settings):
        settings.meeting_archive_bucket = "meetq-archive-test"
        settings.meeting_recording_enabled = True
        settings.archive_summary_wait_seconds = 300
        self.settings = settings
        self.db = FakeMongoDatabase()
        self.redis = FakeRedis()
        self.storage = MemoryStorage()
        self.egress = FakeEgress()
        self.egress.storage = self.storage
        self.events = []
        self.errors = []
        self.ended = set()
        self.live = set()
        self.repo = ArchiveRepository(self.db, default_retention_days=7)
        # The archive lifecycle was switched on a day ago; earlier meetings are legacy.
        self.managed_since = utcnow() - timedelta(days=1)
        self.db["system_settings"].docs.append({"_id": "archive_lifecycle", "managed_since": self.managed_since})

        async def publish(event_type, room_id, payload):
            self.events.append((event_type, payload["recording"]["status"]))

        async def room_ended(room_id):
            return room_id in self.ended

        async def room_is_live(room_id):
            return room_id in self.live

        async def report(room_id, code, detail, details):
            self.errors.append((room_id, code, detail))

        self.archives = ArchiveService(settings, self.repo, self.storage, room_is_live=room_is_live, report_error=report)
        self.recordings = RecordingService(
            settings,
            self.repo,
            self.storage,
            self.egress,
            self.redis,
            publish=publish,
            room_ended=room_ended,
            on_recording_changed=self.archives.refresh_recordings,
            report_error=report,
        )

    async def start(self, name="Huy", participant="pt_huy", user="usr_huy", room=ROOM):
        return await self.recordings.start(room, participant_id=participant, display_name=name, user_id=user, room_languages=["vi", "ja"])

    def event_types(self):
        return [event for event, _status in self.events]

    async def end_meeting(self, room=ROOM, ended_ago=timedelta(minutes=10), summary_status="completed", user_ids=("usr_huy", "usr_kenji")):
        ended = utcnow() - ended_ago
        await self.db["rooms"].insert_one(
            {
                "room_id": room,
                "room_languages": ["vi", "ja"],
                "created_at": (ended - timedelta(minutes=20)).isoformat(),
                "activated_at": (ended - timedelta(minutes=20)).isoformat(),
                "ended_at": ended.isoformat(),
                "ended_at_dt": ended,
                "participant_summaries": [{"display_name": "Huy"}],
                "status_summary": {"state": "empty", "terminal": True, "reason": "empty:rest_leave"},
            }
        )
        for user_id, (pid, name, lang) in zip(user_ids, [("pt_huy", "Huy", "vi"), ("pt_kenji", "Kenji", "ja")]):
            await self.db["room_participants"].insert_one(
                {"room_id": room, "participant_id": pid, "display_name": name, "language": lang, "kind": "human", "user_id": user_id}
            )
        for kind, text in [("source", "Xin chào"), ("relay", "こんにちは"), ("chat", "hi all"), ("translated", "Hello")]:
            await self.db["room_messages"].insert_one({"room_id": room, "kind": kind, "text": text, "created_at": ended.isoformat()})
        if summary_status:
            await self.db["meeting_summaries"].insert_one(
                {"room_id": room, "summary_type": "final", "status": summary_status, "content": {"overview": "Discussed deploy"}}
            )
        return ended


@pytest.fixture
def h(fake_settings):
    return Harness(fake_settings)


# ── Recording lifecycle ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_goes_idle_to_recording_and_notifies_room(h):
    state = await h.start()
    assert state["status"] == "recording"
    assert state["started_by"]["display_name"] == "Huy"
    assert h.event_types() == [EventType.RECORDING_STARTING, EventType.RECORDING_STARTED]
    call = h.egress.start_calls[0]
    assert call["room_name"] == ROOM and call["layout"] == "speaker"
    assert call["object_key"] == f"meetings/{ROOM}/arc_abc123/recordings/{state['recording_id']}.mp4"
    archive = await h.repo.get_archive_by_room(ROOM)
    assert archive["default_retention_days_snapshot"] == 7 and archive["status"] == "open"


@pytest.mark.asyncio
async def test_starting_until_egress_is_active(h):
    h.egress.start_state = JOB_STARTING
    state = await h.start()
    assert state["status"] == "starting"
    h.egress.set_state("EG_1", JOB_ACTIVE)
    await h.recordings.reconcile_once()
    assert (await h.recordings.current(ROOM))["status"] == "recording"
    assert h.event_types()[-1] == EventType.RECORDING_STARTED


@pytest.mark.asyncio
async def test_duplicate_and_concurrent_starts_create_one_job(h):
    first, second, third = await asyncio.gather(h.start(), h.start(name="Kenji", participant="pt_kenji"), h.start())
    assert first["recording_id"] == second["recording_id"] == third["recording_id"]
    assert len(h.egress.start_calls) == 1
    assert len(await h.repo.list_recordings(ROOM)) == 1


@pytest.mark.asyncio
async def test_stop_goes_through_processing_to_ready(h):
    rec = await h.start()
    stopped = await h.recordings.stop(ROOM, rec["recording_id"], reason="user_stopped", stopped_by_name="Kenji")
    assert stopped["status"] == "processing"
    assert EventType.RECORDING_STOPPING in h.event_types() and EventType.RECORDING_STOPPED in h.event_types()
    h.egress.complete("EG_1", size=184_000_000, duration=1722.0)
    await h.recordings.reconcile_once()
    ready = public_recording(await h.repo.get_recording(rec["recording_id"]))
    assert ready["status"] == "ready" and ready["size_bytes"] == 184_000_000 and ready["duration_seconds"] == 1722.0
    assert h.event_types()[-1] == EventType.RECORDING_READY
    assert await h.recordings.current(ROOM) is None  # indicator off


@pytest.mark.asyncio
async def test_duplicate_and_concurrent_stops_are_idempotent(h):
    rec = await h.start()
    results = await asyncio.gather(*[h.recordings.stop(ROOM, rec["recording_id"], reason="user_stopped") for _ in range(3)])
    assert {r["recording_id"] for r in results} == {rec["recording_id"]}
    assert h.egress.stop_calls == ["EG_1"]
    again = await h.recordings.stop(ROOM, rec["recording_id"], reason="user_stopped")
    assert again["status"] == "processing" and h.egress.stop_calls == ["EG_1"]


@pytest.mark.asyncio
async def test_stop_racing_room_expiry_finalizes_once(h):
    rec = await h.start()
    h.ended.add(ROOM)
    await asyncio.gather(
        h.recordings.stop(ROOM, rec["recording_id"], reason="user_stopped"),
        h.recordings.stop_for_room_end(ROOM, "room_expired"),
        h.recordings.reconcile_once(),
    )
    assert h.egress.stop_calls == ["EG_1"]
    h.egress.complete("EG_1")
    await asyncio.gather(h.recordings.reconcile_once(), h.recordings.reconcile_once())
    assert h.event_types().count(EventType.RECORDING_READY) == 1


@pytest.mark.asyncio
async def test_room_end_auto_stops_recording(h):
    rec = await h.start()
    h.ended.add(ROOM)
    await h.recordings.reconcile_once()
    doc = await h.repo.get_recording(rec["recording_id"])
    assert doc["status"] == "processing" and doc["stop_reason"] == "room_ended"


@pytest.mark.asyncio
async def test_recording_continues_when_starter_leaves_or_disconnects(h):
    rec = await h.start()
    # The starter's browser is gone but the room is still running: nothing stops.
    for _ in range(3):
        await h.recordings.reconcile_once()
    assert (await h.recordings.current(ROOM))["recording_id"] == rec["recording_id"]
    assert h.egress.stop_calls == []


@pytest.mark.asyncio
async def test_provider_failure_marks_failed_and_reports(h):
    h.egress.fail_start = True
    with pytest.raises(RecordingError) as excinfo:
        await h.start()
    assert excinfo.value.code == "recording_failed"
    latest = await h.repo.latest_recording(ROOM)
    assert latest["status"] == "failed" and latest["error_code"] == "recording_provider_unavailable"
    assert h.event_types()[-1] == EventType.RECORDING_FAILED
    assert h.errors and h.errors[0][1] == "recording_failed"
    # A later attempt is allowed (no stuck "active" lock).
    h.egress.fail_start = False
    assert (await h.start())["status"] == "recording"


@pytest.mark.asyncio
async def test_egress_failure_mid_recording(h):
    rec = await h.start()
    h.egress.set_state("EG_1", JOB_FAILED, error="pipeline crashed")
    await h.recordings.reconcile_once()
    doc = await h.repo.get_recording(rec["recording_id"])
    assert doc["status"] == "failed" and doc["error_code"] == "recording_provider_failed"
    assert "pipeline crashed" in doc["error_message_internal"]
    assert "error_message_internal" not in public_recording(doc)


@pytest.mark.asyncio
async def test_completed_job_without_s3_object_fails(h):
    rec = await h.start()
    await h.recordings.stop(ROOM, rec["recording_id"], reason="user_stopped")
    h.egress.set_state("EG_1", "complete")  # no object written
    await h.recordings.reconcile_once()
    assert (await h.repo.get_recording(rec["recording_id"]))["error_code"] == "recording_file_missing"


@pytest.mark.asyncio
async def test_segments_never_overwrite_each_other(h):
    first = await h.start()
    await h.recordings.stop(ROOM, first["recording_id"], reason="user_stopped")
    h.egress.complete("EG_1")
    await h.recordings.reconcile_once()
    second = await h.start(name="Kenji", participant="pt_kenji", user="usr_kenji")
    assert second["recording_id"] != first["recording_id"]
    keys = [call["object_key"] for call in h.egress.start_calls]
    assert len(set(keys)) == 2
    assert [r["_id"] for r in await h.repo.list_recordings(ROOM)] == [first["recording_id"], second["recording_id"]]


def test_public_state_hides_internal_fields():
    doc = {
        "_id": "rec_1", "room_id": ROOM, "archive_id": "arc_1", "status": "recording", "started_by_user_id": "usr_secret",
        "started_by_name": "Huy", "s3_key": "meetings/x.mp4", "error_message_internal": "boom", "version": 3,
    }
    state = public_recording(doc)
    assert "s3_key" not in state and "started_by_user_id" not in str(state) and "boom" not in str(state)


# ── Archive ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_meeting_without_recording_is_archived_with_manifest(h):
    ended = await h.end_meeting()
    assert await h.archives.finalize_ended_meetings() == 1
    archive = await h.repo.get_archive_by_room(ROOM)
    assert archive["status"] == "ready"
    assert archive["recording_summary"]["status"] == "none"
    prefix = f"meetings/{ROOM}/arc_abc123/"
    expected = {"meeting.json", "participants.json", "transcript.json", "relay.json", "chat.json", "summaries.json", "manifest.json"}
    assert {k[len(prefix):] for k in h.storage.objects} == expected
    manifest = h.storage.json(prefix + "manifest.json")
    assert manifest["files"]["transcript"] == "transcript.json" and manifest["recordings"] == []
    assert manifest["retention_days"] == 7 and manifest["summary_status"] == "completed"
    assert [m["text"] for m in h.storage.json(prefix + "transcript.json")] == ["Xin chào", "Hello"]
    assert [m["text"] for m in h.storage.json(prefix + "relay.json")] == ["こんにちは"]
    assert [m["text"] for m in h.storage.json(prefix + "chat.json")] == ["hi all"]
    participants = h.storage.json(prefix + "participants.json")
    assert {p["display_name"] for p in participants} == {"Huy", "Kenji"} and all("user_id" not in p for p in participants)
    assert h.storage.tags[prefix + "chat.json"] == {"room_id": ROOM, "archive_id": "arc_abc123", "environment": "local"}
    assert as_utc(archive["expires_at"]) == as_utc(ended) + timedelta(days=7)
    assert archive["participant_user_ids"] == ["usr_huy", "usr_kenji"]
    # Re-running does not rebuild the same meeting end.
    assert await h.archives.finalize_ended_meetings() == 0


@pytest.mark.asyncio
async def test_legacy_meetings_are_not_managed(h):
    # Ended before the lifecycle started: neither archived nor ever deleted automatically.
    await h.end_meeting(room="rm_legacy", ended_ago=timedelta(days=2))
    assert await h.archives.finalize_ended_meetings() == 0
    assert await h.repo.get_archive_by_room("rm_legacy") is None
    assert await h.archives.cleanup_expired() == 0
    assert await h.db["room_messages"].count_documents({"room_id": "rm_legacy"}) == 4


@pytest.mark.asyncio
async def test_archive_waits_for_final_summary(h):
    await h.end_meeting(ended_ago=timedelta(seconds=60), summary_status="pending")
    assert await h.archives.finalize_ended_meetings() == 0
    await h.db["meeting_summaries"].update_one({"room_id": ROOM}, {"$set": {"status": "completed"}})
    assert await h.archives.finalize_ended_meetings() == 1


@pytest.mark.asyncio
async def test_rejoined_room_is_not_archived(h):
    await h.end_meeting()
    h.live.add(ROOM)
    assert await h.archives.finalize_ended_meetings() == 0


@pytest.mark.asyncio
async def test_archive_tracks_recording_until_ready(h):
    rec = await h.start()
    await h.recordings.stop(ROOM, rec["recording_id"], reason="room_ended")
    await h.end_meeting()
    await h.archives.finalize_ended_meetings()
    archive = await h.repo.get_archive_by_room(ROOM)
    assert archive["status"] == "processing_recording"
    h.egress.complete("EG_1", size=1000)
    await h.recordings.reconcile_once()
    archive = await h.repo.get_archive_by_room(ROOM)
    assert archive["status"] == "ready" and archive["recording_summary"]["total_bytes"] == 1000
    manifest = h.storage.json(f"meetings/{ROOM}/arc_abc123/manifest.json")
    assert manifest["recordings"][0]["file"] == f"recordings/{rec['recording_id']}.mp4"


@pytest.mark.asyncio
async def test_failed_recording_keeps_meeting_data_as_partial(h):
    rec = await h.start()
    h.egress.set_state("EG_1", JOB_FAILED, error="x")
    await h.recordings.reconcile_once()
    await h.end_meeting()
    await h.archives.finalize_ended_meetings()
    archive = await h.repo.get_archive_by_room(ROOM)
    assert archive["status"] == "partial"
    assert f"meetings/{ROOM}/arc_abc123/transcript.json" in h.storage.objects


@pytest.mark.asyncio
async def test_upload_failure_is_visible_and_retried(h):
    await h.end_meeting()
    h.storage.fail_puts = 10
    await h.archives.finalize_ended_meetings()
    archive = await h.repo.get_archive_by_room(ROOM)
    assert archive["status"] == "failed" and archive["error_code"] == "archive_upload_failed"
    assert any(code == "archive_failed" for _room, code, _detail in h.errors)
    h.storage.fail_puts = 0
    await h.repo.update_archive(archive["_id"], {"next_attempt_at": utcnow() - timedelta(seconds=1)})
    await h.archives.finalize_ended_meetings()
    assert (await h.repo.get_archive_by_room(ROOM))["status"] == "ready"


# ── Retention ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_global_change_applies_only_to_new_archives(h):
    ended = await h.end_meeting()
    await h.archives.finalize_ended_meetings()
    old = await h.repo.get_archive_by_room(ROOM)
    await h.repo.set_default_retention_days(30, updated_by="ops")
    assert (await h.repo.get_retention_settings())["default_retention_days"] == 30
    unchanged = await h.repo.get_archive_by_room(ROOM)
    assert as_utc(unchanged["expires_at"]) == as_utc(old["expires_at"]) == as_utc(ended) + timedelta(days=7)
    new_ended = await h.end_meeting(room="rm_new")
    await h.archives.finalize_ended_meetings()
    new = await h.repo.get_archive_by_room("rm_new")
    assert new["default_retention_days_snapshot"] == 30
    assert as_utc(new["expires_at"]) == as_utc(new_ended) + timedelta(days=30)


@pytest.mark.asyncio
async def test_per_meeting_override_and_back_to_default(h):
    ended = await h.end_meeting()
    await h.archives.finalize_ended_meetings()
    archive = await h.repo.get_archive_by_room(ROOM)
    updated = await h.repo.set_retention(archive, 30)
    assert as_utc(updated["expires_at"]) == as_utc(ended) + timedelta(days=30)
    reverted = await h.repo.set_retention(updated, None)
    assert as_utc(reverted["expires_at"]) == as_utc(ended) + timedelta(days=7)


@pytest.mark.asyncio
async def test_expired_archive_is_deleted_from_s3_and_db(h):
    rec = await h.start()
    await h.recordings.stop(ROOM, rec["recording_id"], reason="user_stopped")
    h.egress.complete("EG_1")
    await h.recordings.reconcile_once()
    await h.end_meeting(ended_ago=timedelta(days=8))
    await h.repo.update_archive("arc_abc123", {})
    archive = await h.archives.build_archive(await h.db["rooms"].find_one({"room_id": ROOM}))
    assert archive["status"] == "ready" and as_utc(archive["expires_at"]) < utcnow()
    assert any(key.endswith(".mp4") for key in h.storage.objects)

    assert await h.archives.cleanup_expired() == 1
    assert h.storage.objects == {}
    for collection in ("room_messages", "room_participants", "meeting_summaries", "meeting_recordings", "rooms"):
        assert await h.db[collection].count_documents({"room_id": ROOM}) == 0, collection
    tombstone = await h.repo.get_archive_by_room(ROOM)
    assert tombstone["status"] == "deleted" and tombstone["deletion_reason"] == "retention_expired"
    assert tombstone["participant_user_ids"] == [] and tombstone["files"] == {}
    # Idempotent: a second run (or an already-empty prefix) is fine.
    assert await h.archives.cleanup_expired() == 0
    assert await h.storage.delete_prefix(f"meetings/{ROOM}/arc_abc123/") == 0


@pytest.mark.asyncio
async def test_cleanup_retries_after_partial_failure(h):
    await h.end_meeting(ended_ago=timedelta(days=9))
    archive = await h.archives.build_archive(await h.db["rooms"].find_one({"room_id": ROOM}))

    async def boom(prefix):
        raise RuntimeError("s3 down")

    real = h.storage.delete_prefix
    h.storage.delete_prefix = boom
    assert await h.archives.cleanup_expired() == 0
    assert (await h.repo.get_archive(archive["_id"]))["status"] == "deleting"
    h.storage.delete_prefix = real
    assert await h.archives.cleanup_expired() == 1
    assert (await h.repo.get_archive(archive["_id"]))["status"] == "deleted"


@pytest.mark.asyncio
async def test_live_meeting_cannot_be_deleted(h):
    await h.end_meeting()
    archive = await h.archives.build_archive(await h.db["rooms"].find_one({"room_id": ROOM}))
    h.live.add(ROOM)
    from server.service.archive.archive_service import ArchiveError

    with pytest.raises(ArchiveError):
        await h.archives.delete_archive(archive, reason="admin_deleted")
