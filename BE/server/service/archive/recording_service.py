"""Room-level meeting recording: start/stop, state, provider reconciliation.

Invariants
- No hidden recording: every state change is broadcast to the room
  (`recording.*` events) and returned in room snapshots; only participants can start.
- One active recording per room: per-room asyncio lock + Redis lock + a partial
  unique Mongo index on `{room_id, active: true}`.
- Exactly-once finalization: every transition is a compare-and-set on status.
- A recording failure never touches the meeting (relay, chat, media continue).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any, Awaitable, Callable, Dict, Optional

from server.config import Settings
from server.events import EventType
from server.service.archive.egress import (
    JOB_ACTIVE,
    JOB_COMPLETE,
    JOB_ENDING,
    JOB_FAILED,
    RecordingJob,
    RecordingProvider,
    RecordingProviderError,
)
from server.service.archive.repository import (
    REC_ACTIVE_STATUSES,
    REC_FAILED,
    REC_PENDING_STATUSES,
    REC_PROCESSING,
    REC_READY,
    REC_RECORDING,
    REC_STARTING,
    REC_STOPPING,
    ArchiveRepository,
    new_recording_id,
)
from server.service.archive.retention import as_utc, iso, utcnow
from server.service.archive.storage import ArchiveStorage

logger = logging.getLogger(__name__)

Publish = Callable[[str, str, Dict[str, Any]], Awaitable[None]]
RoomEnded = Callable[[str], Awaitable[bool]]

START_TIMEOUT = timedelta(seconds=90)
MISSING_JOB_GRACE = timedelta(minutes=2)
_LOCK_KEY = "brseai:v1:recording:lock:{room_id}"
_LOCK_TTL_SECONDS = 30

_EVENT_FOR_STATUS = {
    REC_STARTING: EventType.RECORDING_STARTING,
    REC_RECORDING: EventType.RECORDING_STARTED,
    REC_STOPPING: EventType.RECORDING_STOPPING,
    REC_PROCESSING: EventType.RECORDING_PROCESSING,
    REC_READY: EventType.RECORDING_READY,
    REC_FAILED: EventType.RECORDING_FAILED,
}


class RecordingError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def public_recording(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """What participants and users may see. No S3 keys, user IDs or internal errors."""
    if not doc:
        return None
    return {
        "recording_id": doc["_id"],
        "room_id": doc["room_id"],
        "archive_id": doc.get("archive_id"),
        "status": doc["status"],
        "requested_at": iso(doc.get("requested_at")),
        "started_at": iso(doc.get("started_at")),
        "stopped_at": iso(doc.get("stopped_at")),
        "duration_seconds": doc.get("duration_seconds"),
        "size_bytes": doc.get("size_bytes"),
        "started_by": {
            "participant_id": doc.get("started_by_participant_id"),
            "display_name": doc.get("started_by_name"),
        },
        "stopped_by": doc.get("stopped_by_name"),
        "stop_reason": doc.get("stop_reason"),
        "error_code": doc.get("error_code"),
        "version": int(doc.get("version") or 1),
    }


class RecordingService:
    def __init__(
        self,
        settings: Settings,
        repo: ArchiveRepository,
        storage: Optional[ArchiveStorage],
        provider: Optional[RecordingProvider],
        redis: Any,
        *,
        publish: Publish,
        room_ended: RoomEnded,
        on_recording_changed: Optional[Callable[[str], Awaitable[None]]] = None,
        report_error: Optional[Callable[[str, str, str, Dict[str, Any]], Awaitable[None]]] = None,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.storage = storage
        self.provider = provider
        self.redis = redis
        self._publish = publish
        self._room_ended = room_ended
        self._on_changed = on_recording_changed
        self._report_error = report_error
        self._locks: Dict[str, asyncio.Lock] = {}

    @property
    def available(self) -> bool:
        return bool(
            self.settings.meeting_recording_enabled
            and self.repo.enabled
            and self.storage is not None
            and self.provider is not None
        )

    # ── Locking ─────────────────────────────────────────────────────────────

    def _local_lock(self, room_id: str) -> asyncio.Lock:
        lock = self._locks.get(room_id)
        if lock is None:
            lock = self._locks[room_id] = asyncio.Lock()
        return lock

    async def _acquire_redis_lock(self, room_id: str) -> bool:
        for _ in range(50):
            if await self.redis.set(_LOCK_KEY.format(room_id=room_id), "1", ex=_LOCK_TTL_SECONDS, nx=True):
                return True
            await asyncio.sleep(0.1)
        return False

    async def _release_redis_lock(self, room_id: str) -> None:
        await self.redis.delete(_LOCK_KEY.format(room_id=room_id))

    class _RoomLock:
        def __init__(self, service: "RecordingService", room_id: str) -> None:
            self.service = service
            self.room_id = room_id
            self.local = service._local_lock(room_id)

        async def __aenter__(self) -> None:
            await self.local.acquire()
            if not await self.service._acquire_redis_lock(self.room_id):
                self.local.release()
                raise RecordingError(409, "recording_busy", "Another recording change is in progress. Try again.")

        async def __aexit__(self, *exc: Any) -> None:
            try:
                await self.service._release_redis_lock(self.room_id)
            finally:
                self.local.release()

    def _room_lock(self, room_id: str) -> "RecordingService._RoomLock":
        return RecordingService._RoomLock(self, room_id)

    # ── Queries ─────────────────────────────────────────────────────────────

    async def current(self, room_id: str) -> Optional[Dict[str, Any]]:
        """The active recording (starting/recording/stopping) shown as the room indicator."""
        if not self.repo.enabled:
            return None
        return public_recording(await self.repo.active_recording(room_id))

    # ── Commands ────────────────────────────────────────────────────────────

    async def start(
        self,
        room_id: str,
        *,
        participant_id: str,
        display_name: str,
        user_id: Optional[str],
        room_languages: Optional[list] = None,
    ) -> Dict[str, Any]:
        if not self.available:
            raise RecordingError(503, "recording_unavailable", "Recording isn't available on this server.")
        async with self._room_lock(room_id):
            existing = await self.repo.active_recording(room_id)
            if existing:
                # Idempotent: a second Record click joins the running recording.
                return public_recording(existing)

            archive = await self.repo.ensure_archive(room_id, room_languages=room_languages)
            recording_id = new_recording_id()
            object_key = f"{self.settings.meeting_archive_prefix}/{room_id}/{archive['_id']}/recordings/{recording_id}.mp4"
            now = utcnow()
            doc = {
                "_id": recording_id,
                "recording_id": recording_id,
                "room_id": room_id,
                "archive_id": archive["_id"],
                "status": REC_STARTING,
                "active": True,
                "version": 1,
                "started_by_user_id": user_id,
                "started_by_participant_id": participant_id,
                "started_by_name": display_name,
                "requested_at": now,
                "started_at": None,
                "stopped_at": None,
                "duration_seconds": None,
                "size_bytes": None,
                "provider": "livekit_egress",
                "provider_recording_id": None,
                "s3_bucket": self.storage.bucket if self.storage else None,
                "s3_key": object_key,
                "error_code": None,
                "error_message_internal": None,
                "created_at": now,
                "updated_at": now,
            }
            try:
                await self.repo.insert_recording(doc)
            except Exception as exc:
                if "duplicate key" in str(exc).lower():
                    return public_recording(await self.repo.active_recording(room_id))
                raise
            self._log("recording start requested", doc)
            await self._emit(doc)

            try:
                job = await self.provider.start(room_name=room_id, object_key=object_key, layout=self.settings.recording_layout)
            except RecordingProviderError as exc:
                failed = await self._fail(doc, exc.code, str(exc))
                raise RecordingError(503, "recording_failed", "Recording couldn't start. The meeting continues normally.") from exc
            fields: Dict[str, Any] = {"provider_recording_id": job.job_id}
            if job.state == JOB_ACTIVE:
                fields.update(status=REC_RECORDING, started_at=job.started_at or utcnow())
            updated = await self.repo.update_recording(recording_id, fields, expected_statuses=[REC_STARTING])
            if updated and updated["status"] == REC_RECORDING:
                await self._emit(updated)
            await self._changed(room_id)
            return public_recording(updated or await self.repo.get_recording(recording_id))

    async def stop(
        self,
        room_id: str,
        recording_id: str,
        *,
        reason: str,
        stopped_by_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        async with self._room_lock(room_id):
            doc = await self.repo.get_recording(recording_id)
            if doc is None or doc["room_id"] != room_id:
                raise RecordingError(404, "recording_not_found", "Recording not found.")
            if doc["status"] not in (REC_STARTING, REC_RECORDING):
                # Idempotent: already stopping, processing, ready or failed.
                return public_recording(doc)
            stopping = await self.repo.update_recording(
                recording_id,
                {
                    "status": REC_STOPPING,
                    "stop_requested_at": utcnow(),
                    "stop_reason": reason,
                    "stopped_by_name": stopped_by_name,
                },
                expected_statuses=[REC_STARTING, REC_RECORDING],
            )
            if stopping is None:
                return public_recording(await self.repo.get_recording(recording_id))
            self._log("recording stop requested", stopping, reason=reason)
            await self._emit(stopping)
            if stopping.get("provider_recording_id") and self.provider is not None:
                try:
                    job = await self.provider.stop(stopping["provider_recording_id"])
                    if job is not None:
                        await self._apply_job(stopping, job)
                except Exception:
                    # The reconciler retries; the room is never affected.
                    logger.warning("recording stop call failed room_id=%s recording_id=%s", room_id, recording_id, exc_info=True)
            await self._changed(room_id)
            return public_recording(await self.repo.get_recording(recording_id))

    async def stop_for_room_end(self, room_id: str, reason: str = "room_ended") -> None:
        if not self.repo.enabled:
            return
        active = await self.repo.active_recording(room_id)
        if active and active["status"] in (REC_STARTING, REC_RECORDING):
            try:
                await self.stop(room_id, active["_id"], reason=reason)
            except RecordingError:
                logger.warning("auto-stop deferred room_id=%s recording_id=%s", room_id, active["_id"])

    # ── Reconciliation (background worker) ─────────────────────────────────

    async def reconcile_once(self) -> None:
        if not self.repo.enabled or self.provider is None:
            return
        for doc in await self.repo.pending_recordings():
            try:
                await self._reconcile(doc)
            except Exception:
                logger.exception("recording reconcile failed recording_id=%s", doc.get("_id"))

    async def _reconcile(self, doc: Dict[str, Any]) -> None:
        now = utcnow()
        if doc["status"] in (REC_STARTING, REC_RECORDING) and await self._room_ended(doc["room_id"]):
            await self.stop(doc["room_id"], doc["_id"], reason="room_ended")
            doc = await self.repo.get_recording(doc["_id"]) or doc
            if doc["status"] not in REC_PENDING_STATUSES:
                return

        job_id = doc.get("provider_recording_id")
        requested_at = as_utc(doc.get("requested_at")) or now
        if not job_id:
            if doc["status"] == REC_STARTING and now - requested_at > START_TIMEOUT:
                await self._fail(doc, "recording_start_timeout", "no egress job after start request")
            return
        job = await self.provider.get(job_id)
        if job is None:
            if now - requested_at > MISSING_JOB_GRACE:
                await self._fail(doc, "recording_job_missing", "egress job not found")
            return
        if doc["status"] == REC_STARTING and job.state not in (JOB_ACTIVE, JOB_ENDING, JOB_COMPLETE, JOB_FAILED):
            if now - requested_at > START_TIMEOUT:
                await self.provider.stop(job_id)
                await self._fail(doc, "recording_start_timeout", "egress did not become active")
            return
        await self._apply_job(doc, job)

    async def _apply_job(self, doc: Dict[str, Any], job: RecordingJob) -> None:
        recording_id = doc["_id"]
        if job.state == JOB_ACTIVE and doc["status"] == REC_STARTING:
            updated = await self.repo.update_recording(
                recording_id,
                {"status": REC_RECORDING, "started_at": job.started_at or utcnow()},
                expected_statuses=[REC_STARTING],
            )
            if updated:
                self._log("recording started", updated)
                await self._emit(updated)
            return
        if job.state == JOB_ENDING and doc["status"] in REC_ACTIVE_STATUSES:
            updated = await self.repo.update_recording(
                recording_id,
                {"status": REC_PROCESSING, "stopped_at": job.ended_at or utcnow()},
                expected_statuses=list(REC_ACTIVE_STATUSES),
            )
            if updated:
                await self._emit_stopped(updated)
                await self._emit(updated)
            return
        if job.state == JOB_COMPLETE and doc["status"] in REC_PENDING_STATUSES:
            await self._complete(doc, job)
            return
        if job.state == JOB_FAILED and doc["status"] in REC_PENDING_STATUSES:
            await self._fail(doc, "recording_provider_failed", job.error or "egress failed")

    async def _complete(self, doc: Dict[str, Any], job: RecordingJob) -> None:
        size = job.size_bytes
        if self.storage is not None:
            stored = await self.storage.head(doc["s3_key"])
            if stored is None:
                await self._fail(doc, "recording_file_missing", "egress completed but the object is not in S3")
                return
            size = stored.size
        started_at = as_utc(doc.get("started_at")) or job.started_at
        stopped_at = as_utc(doc.get("stopped_at")) or job.ended_at or utcnow()
        duration = job.duration_seconds
        if duration is None and started_at:
            duration = max(0.0, (stopped_at - started_at).total_seconds())
        was_active = doc["status"] in REC_ACTIVE_STATUSES
        updated = await self.repo.update_recording(
            doc["_id"],
            {
                "status": REC_READY,
                "started_at": started_at,
                "stopped_at": stopped_at,
                "duration_seconds": round(duration, 1) if duration is not None else None,
                "size_bytes": size,
            },
            expected_statuses=list(REC_PENDING_STATUSES),
        )
        if updated:
            self._log("recording ready", updated, size_bytes=size)
            if was_active:
                await self._emit_stopped(updated)
            await self._emit(updated)
            await self._changed(doc["room_id"])

    async def _fail(self, doc: Dict[str, Any], code: str, internal_message: str) -> Optional[Dict[str, Any]]:
        updated = await self.repo.update_recording(
            doc["_id"],
            {
                "status": REC_FAILED,
                "error_code": code,
                "error_message_internal": internal_message[:500],
                "stopped_at": as_utc(doc.get("stopped_at")) or utcnow(),
            },
            expected_statuses=list(REC_PENDING_STATUSES),
        )
        if updated is None:
            return None
        self._log("recording failed", updated, error_code=code, level=logging.WARNING)
        await self._emit(updated)
        await self._changed(doc["room_id"])
        if self._report_error is not None:
            try:
                await self._report_error(doc["room_id"], "recording_failed", code, {"recording_id": doc["_id"]})
            except Exception:
                logger.debug("recording failure report failed", exc_info=True)
        return updated

    # ── Helpers ─────────────────────────────────────────────────────────────

    async def _emit(self, doc: Dict[str, Any]) -> None:
        event_type = _EVENT_FOR_STATUS.get(doc["status"])
        if event_type:
            await self._publish(event_type, doc["room_id"], {"recording": public_recording(doc)})

    async def _emit_stopped(self, doc: Dict[str, Any]) -> None:
        await self._publish(EventType.RECORDING_STOPPED, doc["room_id"], {"recording": public_recording(doc)})

    async def _changed(self, room_id: str) -> None:
        if self._on_changed is not None:
            try:
                await self._on_changed(room_id)
            except Exception:
                logger.warning("archive recording summary refresh failed room_id=%s", room_id, exc_info=True)

    @staticmethod
    def _log(message: str, doc: Dict[str, Any], *, level: int = logging.INFO, **extra: Any) -> None:
        bits = " ".join(f"{key}={value}" for key, value in extra.items())
        logger.log(
            level,
            "%s room_id=%s archive_id=%s recording_id=%s provider_job_id=%s status=%s %s",
            message,
            doc.get("room_id"),
            doc.get("archive_id"),
            doc.get("_id"),
            doc.get("provider_recording_id"),
            doc.get("status"),
            bits,
        )
