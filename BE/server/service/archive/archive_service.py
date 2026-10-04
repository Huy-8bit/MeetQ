"""Meeting archive: finalize ended meetings to S3, track recordings, enforce retention.

Lifecycle of one archive (one per room):

  open ──(meeting ends)──> finalizing ──upload JSON + manifest──> processing_recording
                                    │                                  │ (all segments terminal)
                                    └──── no pending recordings ───────┴──> ready | partial
  upload error ──> failed (retried with backoff, visible to admins)
  expires_at <= now or admin delete ──> deleting ──> deleted (tombstone, no content)

MongoDB stays the source of truth for live data; S3 receives a consistent snapshot
after the meeting ends. Meetings that ended before the lifecycle started are legacy
and are neither archived nor deleted automatically.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Callable, Dict, List, Optional, Awaitable

from server.config import Settings
from server.service.archive.repository import (
    ARCHIVE_DELETED,
    ARCHIVE_DELETING,
    ARCHIVE_FAILED,
    ARCHIVE_FINALIZING,
    ARCHIVE_OPEN,
    ARCHIVE_PARTIAL,
    ARCHIVE_PROCESSING_RECORDING,
    ARCHIVE_READY,
    REC_FAILED,
    REC_PENDING_STATUSES,
    REC_READY,
    ArchiveRepository,
)
from server.service.archive.retention import (
    as_utc,
    compute_expires_at,
    effective_retention_days,
    iso,
    utcnow,
)
from server.service.archive.storage import ArchiveStorage, StorageError

logger = logging.getLogger(__name__)

ROOMS = "rooms"
PARTICIPANTS = "room_participants"
MESSAGES = "room_messages"
SUMMARIES = "meeting_summaries"

ARCHIVE_SCHEMA_VERSION = 1
CANDIDATE_LOOKBACK = timedelta(days=3)
MAX_RETRY_DELAY = timedelta(hours=1)
SUMMARY_TERMINAL_STATUSES = {"completed", "skipped", "failed", "not_enough_content", "insufficient_content"}

FILES = {
    "meeting": "meeting.json",
    "participants": "participants.json",
    "transcript": "transcript.json",
    "relay": "relay.json",
    "chat": "chat.json",
    "summaries": "summaries.json",
}

RoomIsLive = Callable[[str], Awaitable[bool]]
ReportError = Callable[[str, str, str, Dict[str, Any]], Awaitable[None]]


class ArchiveError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def _clean(doc: Dict[str, Any], drop: tuple = ()) -> Dict[str, Any]:
    """JSON-safe copy without Mongo internals or `*_dt` duplicates."""
    result: Dict[str, Any] = {}
    for key, value in doc.items():
        if key == "_id" or key.endswith("_dt") or key in drop:
            continue
        if hasattr(value, "isoformat"):
            value = iso(value)
        result[key] = value
    return result


def recording_summary(recordings: List[Dict[str, Any]]) -> Dict[str, Any]:
    ready = [r for r in recordings if r["status"] == REC_READY]
    failed = [r for r in recordings if r["status"] == REC_FAILED]
    pending = [r for r in recordings if r["status"] in REC_PENDING_STATUSES]
    if not recordings:
        status = "none"
    elif pending:
        status = "processing"
    elif failed and ready:
        status = "partial"
    elif failed:
        status = "failed"
    else:
        status = "ready"
    return {
        "status": status,
        "count": len(recordings),
        "ready": len(ready),
        "failed": len(failed),
        "pending": len(pending),
        "total_bytes": sum(int(r.get("size_bytes") or 0) for r in ready),
        "total_duration_seconds": round(sum(float(r.get("duration_seconds") or 0) for r in ready), 1),
    }


class ArchiveService:
    def __init__(
        self,
        settings: Settings,
        repo: ArchiveRepository,
        storage: Optional[ArchiveStorage],
        *,
        room_is_live: RoomIsLive,
        report_error: Optional[ReportError] = None,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.storage = storage
        self._room_is_live = room_is_live
        self._report_error = report_error

    @property
    def db(self) -> Any:
        return self.repo.db

    @property
    def enabled(self) -> bool:
        return self.repo.enabled

    def prefix(self, archive: Dict[str, Any]) -> str:
        return f"{self.settings.meeting_archive_prefix}/{archive['room_id']}/{archive['_id']}/"

    # ── Finalization ────────────────────────────────────────────────────────

    async def finalize_ended_meetings(self, *, limit: int = 20) -> int:
        """Archives meetings that ended since the lifecycle started (bounded scan)."""
        if not self.enabled:
            return 0
        managed_since = await self.repo.managed_since()
        window_start = max(managed_since, utcnow() - CANDIDATE_LOOKBACK)
        rooms = await self.db[ROOMS].find(
            {"status_summary.terminal": True, "ended_at_dt": {"$gte": window_start}}
        ).sort("ended_at_dt", 1).limit(200).to_list(length=200)
        done = 0
        for room in rooms:
            if done >= limit:
                break
            archive = await self.repo.get_archive_by_room(room["room_id"])
            if archive and archive["status"] in (ARCHIVE_DELETING, ARCHIVE_DELETED):
                continue
            if archive and archive["status"] != ARCHIVE_OPEN and iso(archive.get("ended_at")) == iso(room.get("ended_at_dt") or room.get("ended_at")):
                continue  # already archived for this end of the meeting
            if archive and archive["status"] == ARCHIVE_FAILED and not self._retry_due(archive):
                continue
            if await self._room_is_live(room["room_id"]):
                continue  # someone rejoined; archive when it ends again
            if not await self._summary_settled(room):
                continue
            await self.build_archive(room)
            done += 1
        done += await self._retry_failed(limit=limit - done)
        return done

    def _retry_due(self, archive: Dict[str, Any]) -> bool:
        next_attempt = as_utc(archive.get("next_attempt_at"))
        return next_attempt is None or next_attempt <= utcnow()

    async def _retry_failed(self, *, limit: int) -> int:
        if limit <= 0:
            return 0
        failed = await self.repo.list_archives({"status": ARCHIVE_FAILED}, sort="next_attempt_at", direction=1, limit=limit)
        count = 0
        for archive in failed:
            if not self._retry_due(archive):
                continue
            room = await self.db[ROOMS].find_one({"room_id": archive["room_id"]})
            if room:
                await self.build_archive(room)
                count += 1
        return count

    async def _summary_settled(self, room: Dict[str, Any]) -> bool:
        ended_at = as_utc(room.get("ended_at_dt") or room.get("ended_at"))
        if ended_at and utcnow() - ended_at >= timedelta(seconds=self.settings.archive_summary_wait_seconds):
            return True  # don't hold the archive forever; manifest records the summary state
        summary = await self.db[SUMMARIES].find_one({"room_id": room["room_id"], "summary_type": "final"})
        if summary is None:
            # No summary requested (e.g. Mongo summary disabled): give the end flow a moment.
            return bool(ended_at and utcnow() - ended_at >= timedelta(seconds=30))
        return str(summary.get("status") or "") in SUMMARY_TERMINAL_STATUSES

    async def build_archive(self, room: Dict[str, Any]) -> Dict[str, Any]:
        room_id = room["room_id"]
        archive = await self.repo.ensure_archive(room_id, room_languages=room.get("room_languages") or [])
        ended_at = as_utc(room.get("ended_at_dt") or room.get("ended_at")) or utcnow()
        participants = await self.db[PARTICIPANTS].find({"room_id": room_id}).to_list(length=1000)
        user_ids = sorted({p["user_id"] for p in participants if p.get("user_id")})
        base_fields = {
            "status": ARCHIVE_FINALIZING,
            "ended_at": ended_at,
            "meeting_started_at": as_utc(room.get("activated_at") or room.get("created_at")),
            "room_languages": room.get("room_languages") or archive.get("room_languages") or [],
            "participant_user_ids": user_ids,
            "participant_count": len([p for p in participants if p.get("kind", "human") == "human"]),
            "end_reason": (room.get("status_summary") or {}).get("reason"),
        }
        archive = await self.repo.update_archive(archive["_id"], base_fields)
        archive = await self.repo.update_archive(archive["_id"], {"expires_at": compute_expires_at(archive)})
        self._log("archive finalizing", archive)

        if self.storage is None:
            # No archive bucket: data stays in MongoDB only, retention still applies.
            return await self._settle(archive, files={}, storage="none")

        try:
            files = await self._upload_content(archive, room, participants)
            recordings = await self.repo.list_recordings(room_id)
            manifest = self._manifest(archive, files, recordings, await self._summary_status(room_id))
            stored = await self.storage.put_json(self.prefix(archive) + "manifest.json", manifest, tags=self._tags(archive))
            files["manifest"] = {"key": stored.key, "size": stored.size}
        except StorageError as exc:
            attempts = int(archive.get("attempts") or 0) + 1
            delay = min(MAX_RETRY_DELAY, timedelta(minutes=2 ** min(attempts, 6)))
            archive = await self.repo.update_archive(
                archive["_id"],
                {
                    "status": ARCHIVE_FAILED,
                    "attempts": attempts,
                    "next_attempt_at": utcnow() + delay,
                    "error_code": "archive_upload_failed",
                    "error_message_internal": str(exc)[:500],
                },
            )
            self._log("archive upload failed", archive, level=logging.ERROR, attempts=attempts)
            await self._report(archive, "archive_failed", "archive_upload_failed")
            return archive
        return await self._settle(archive, files=files, storage="s3")

    async def _settle(self, archive: Dict[str, Any], *, files: Dict[str, Any], storage: str) -> Dict[str, Any]:
        recordings = await self.repo.list_recordings(archive["room_id"])
        summary = recording_summary(recordings)
        status = self._status_for(summary)
        archive = await self.repo.update_archive(
            archive["_id"],
            {
                "status": status,
                "storage": storage,
                "s3_bucket": self.storage.bucket if self.storage else None,
                "s3_prefix": self.prefix(archive) if self.storage else None,
                "files": files,
                "recording_summary": summary,
                "finalized_at": utcnow(),
                "attempts": 0,
                "error_code": None,
            },
            unset=("next_attempt_at", "error_message_internal"),
        )
        self._log("archive finalized", archive, files=len(files), recordings=summary["count"])
        return archive

    @staticmethod
    def _status_for(summary: Dict[str, Any]) -> str:
        if summary["pending"]:
            return ARCHIVE_PROCESSING_RECORDING
        if summary["failed"]:
            return ARCHIVE_PARTIAL
        return ARCHIVE_READY

    async def _upload_content(
        self,
        archive: Dict[str, Any],
        room: Dict[str, Any],
        participants: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        room_id = archive["room_id"]
        messages = await self.db[MESSAGES].find({"room_id": room_id}).sort("created_at", 1).to_list(length=100000)
        summaries = await self.db[SUMMARIES].find({"room_id": room_id}).to_list(length=50)
        transcript = [_clean(m) for m in messages if m.get("kind") in ("source", "translated")]
        relay = [_clean(m) for m in messages if m.get("kind") == "relay"]
        chat = [_clean(m) for m in messages if m.get("kind") == "chat"]
        payloads = {
            "meeting": {
                "archive_id": archive["_id"],
                "room": _clean(room, drop=("participant_summaries", "participant_ids", "share_url")),
                "counts": {"transcript": len(transcript), "relay": len(relay), "chat": len(chat)},
            },
            # Display name, language and join/leave times — never emails or user IDs.
            "participants": [_clean(p, drop=("user_id", "client", "sessions", "metadata")) for p in participants],
            "transcript": transcript,
            "relay": relay,
            "chat": chat,
            "summaries": [_clean(s) for s in summaries],
        }
        files: Dict[str, Any] = {}
        for name, filename in FILES.items():
            stored = await self.storage.put_json(self.prefix(archive) + filename, payloads[name], tags=self._tags(archive))
            files[name] = {"key": stored.key, "size": stored.size}
        return files

    async def _summary_status(self, room_id: str) -> str:
        summary = await self.db[SUMMARIES].find_one({"room_id": room_id, "summary_type": "final"})
        return str((summary or {}).get("status") or "none")

    def _manifest(
        self,
        archive: Dict[str, Any],
        files: Dict[str, Any],
        recordings: List[Dict[str, Any]],
        summary_status: str,
    ) -> Dict[str, Any]:
        return {
            "schema_version": ARCHIVE_SCHEMA_VERSION,
            "archive_id": archive["_id"],
            "room_id": archive["room_id"],
            "environment": self.settings.deployment_environment,
            "created_at": iso(archive.get("created_at")),
            "meeting_started_at": iso(archive.get("meeting_started_at")),
            "ended_at": iso(archive.get("ended_at")),
            "expires_at": iso(archive.get("expires_at")),
            "retention_days": effective_retention_days(archive),
            "languages": archive.get("room_languages") or [],
            "summary_status": summary_status,
            "files": {name: FILES[name] for name in files if name in FILES},
            "recordings": [
                {
                    "recording_id": r["_id"],
                    "status": r["status"],
                    "file": f"recordings/{r['_id']}.mp4" if r["status"] == REC_READY else None,
                    "started_at": iso(r.get("started_at")),
                    "stopped_at": iso(r.get("stopped_at")),
                    "duration_seconds": r.get("duration_seconds"),
                    "size_bytes": r.get("size_bytes"),
                }
                for r in recordings
            ],
            "generated_at": iso(utcnow()),
        }

    def _tags(self, archive: Dict[str, Any]) -> Dict[str, str]:
        # Identifiers only: never meeting text in object metadata or tags.
        return {
            "room_id": archive["room_id"],
            "archive_id": archive["_id"],
            "environment": self.settings.deployment_environment,
        }

    async def refresh_recordings(self, room_id: str) -> None:
        """Called when a recording changes: keep archive aggregates and manifest current."""
        archive = await self.repo.get_archive_by_room(room_id)
        if archive is None or archive["status"] in (ARCHIVE_DELETING, ARCHIVE_DELETED):
            return
        recordings = await self.repo.list_recordings(room_id)
        summary = recording_summary(recordings)
        fields: Dict[str, Any] = {"recording_summary": summary}
        if archive["status"] in (ARCHIVE_PROCESSING_RECORDING, ARCHIVE_READY, ARCHIVE_PARTIAL):
            fields["status"] = self._status_for(summary)
            if self.storage is not None and archive.get("files"):
                try:
                    manifest = self._manifest(archive, archive["files"], recordings, await self._summary_status(room_id))
                    await self.storage.put_json(self.prefix(archive) + "manifest.json", manifest, tags=self._tags(archive))
                except StorageError:
                    logger.warning("manifest refresh failed archive_id=%s; will retry", archive["_id"])
                    return
        await self.repo.update_archive(archive["_id"], fields)

    async def settle_processing(self) -> None:
        """Safety net: re-evaluate archives still waiting for recordings."""
        if not self.enabled:
            return
        for archive in await self.repo.list_archives({"status": ARCHIVE_PROCESSING_RECORDING}, limit=50):
            await self.refresh_recordings(archive["room_id"])

    # ── Retention & deletion ────────────────────────────────────────────────

    async def cleanup_expired(self, *, limit: int = 50) -> int:
        if not self.enabled:
            return 0
        now = utcnow()
        due = await self.repo.list_archives(
            {"expires_at": {"$lte": now}, "status": {"$nin": [ARCHIVE_DELETED, ARCHIVE_OPEN]}},
            sort="expires_at",
            direction=1,
            limit=limit,
        )
        deleted = 0
        for archive in due:
            try:
                await self.delete_archive(archive, reason="retention_expired")
                deleted += 1
            except Exception:
                logger.exception("archive cleanup failed archive_id=%s", archive["_id"])
        return deleted

    async def delete_archive(self, archive: Dict[str, Any], *, reason: str, actor: Optional[str] = None) -> Dict[str, Any]:
        """Permanently deletes recordings, archived JSON and meeting content. Idempotent."""
        if archive["status"] == ARCHIVE_DELETED:
            return archive
        if await self._room_is_live(archive["room_id"]):
            raise ArchiveError(409, "meeting_in_progress", "The meeting is still in progress.")
        pending = [r for r in await self.repo.list_recordings(archive["room_id"]) if r["status"] in REC_PENDING_STATUSES]
        if pending:
            raise ArchiveError(409, "recording_in_progress", "A recording is still being finalized. Try again shortly.")
        archive = await self.repo.update_archive(archive["_id"], {"status": ARCHIVE_DELETING, "deletion_reason": reason})
        self._log("archive deleting", archive, reason=reason)
        try:
            removed_objects = 0
            if self.storage is not None:
                # The whole archive prefix: JSON, manifest and every recording segment.
                removed_objects = await self.storage.delete_prefix(self.prefix(archive))
            room_id = archive["room_id"]
            await self.db[MESSAGES].delete_many({"room_id": room_id})
            await self.db[SUMMARIES].delete_many({"room_id": room_id})
            await self.db[PARTICIPANTS].delete_many({"room_id": room_id})
            await self.repo.delete_room_recordings(room_id)
            await self.db[ROOMS].delete_many({"room_id": room_id})
        except Exception as exc:
            self._log("archive delete failed", archive, level=logging.ERROR, reason=reason)
            await self._report(archive, "archive_delete_failed", "archive_delete_failed")
            raise ArchiveError(502, "archive_delete_failed", "Deleting the meeting archive failed; it will be retried.") from exc

        # Tombstone: identifiers and timestamps only, no meeting content or participants.
        archive = await self.repo.update_archive(
            archive["_id"],
            {
                "status": ARCHIVE_DELETED,
                "deleted_at": utcnow(),
                "deletion_reason": reason,
                "deleted_by": actor,
                "files": {},
                "participant_user_ids": [],
                "deleted_object_count": removed_objects,
            },
            unset=("error_message_internal", "next_attempt_at"),
        )
        self._log("archive deleted", archive, reason=reason, objects=removed_objects)
        return archive

    # ── Helpers ─────────────────────────────────────────────────────────────

    async def _report(self, archive: Dict[str, Any], code: str, detail: str) -> None:
        if self._report_error is None:
            return
        try:
            await self._report_error(archive["room_id"], code, detail, {"archive_id": archive["_id"]})
        except Exception:
            logger.debug("archive error report failed", exc_info=True)

    @staticmethod
    def _log(message: str, archive: Dict[str, Any], *, level: int = logging.INFO, **extra: Any) -> None:
        bits = " ".join(f"{key}={value}" for key, value in extra.items())
        logger.log(
            level,
            "%s room_id=%s archive_id=%s status=%s %s",
            message,
            archive.get("room_id"),
            archive.get("_id"),
            archive.get("status"),
            bits,
        )
