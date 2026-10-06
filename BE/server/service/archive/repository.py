"""MongoDB metadata for recordings, meeting archives and retention settings.

Collections:
  system_settings     {_id: "meeting_retention"}  admin default retention
                      {_id: "archive_lifecycle"}  first start of the archive lifecycle
                                                  (meetings that ended before it are legacy)
  meeting_archives    one per room: status, retention, expiry, S3 files, access list
  meeting_recordings  one per recording segment: egress job, S3 key, size, duration
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Iterable, List, Optional

from server.service.archive.retention import (
    as_utc,
    compute_expires_at,
    utcnow,
    validate_retention_days,
)

logger = logging.getLogger(__name__)

SETTINGS = "system_settings"
ARCHIVES = "meeting_archives"
RECORDINGS = "meeting_recordings"

RETENTION_SETTINGS_ID = "meeting_retention"
LIFECYCLE_SETTINGS_ID = "archive_lifecycle"

# Archive status
ARCHIVE_OPEN = "open"  # meeting still running (created when a recording starts)
ARCHIVE_FINALIZING = "finalizing"
ARCHIVE_PROCESSING_RECORDING = "processing_recording"
ARCHIVE_READY = "ready"
ARCHIVE_PARTIAL = "partial"  # meeting data archived, a recording failed
ARCHIVE_FAILED = "failed"  # upload failed; retried with backoff
ARCHIVE_DELETING = "deleting"
ARCHIVE_DELETED = "deleted"
ARCHIVE_LIVE_STATUSES = (ARCHIVE_FINALIZING, ARCHIVE_PROCESSING_RECORDING, ARCHIVE_READY, ARCHIVE_PARTIAL, ARCHIVE_FAILED)

# Recording status (room-level state shown to every participant)
REC_STARTING = "starting"
REC_RECORDING = "recording"
REC_STOPPING = "stopping"
REC_PROCESSING = "processing"
REC_READY = "ready"
REC_FAILED = "failed"
REC_ACTIVE_STATUSES = (REC_STARTING, REC_RECORDING, REC_STOPPING)
REC_PENDING_STATUSES = REC_ACTIVE_STATUSES + (REC_PROCESSING,)
REC_TERMINAL_STATUSES = (REC_READY, REC_FAILED)


def archive_id_for_room(room_id: str) -> str:
    """One archive per room; deterministic so concurrent creators agree."""
    suffix = room_id[3:] if room_id.startswith("rm_") else room_id
    return f"arc_{suffix}"


def new_recording_id() -> str:
    return f"rec_{uuid.uuid4().hex[:16]}"


class ArchiveRepository:
    def __init__(self, db: Any, *, default_retention_days: int) -> None:
        self.db = db
        self.default_retention_days = validate_retention_days(int(default_retention_days))

    @property
    def enabled(self) -> bool:
        return self.db is not None

    async def ensure_indexes(self) -> None:
        if self.db is None:
            return
        await self.db[ARCHIVES].create_index("room_id", unique=True, name="uniq_archive_room")
        await self.db[ARCHIVES].create_index([("status", 1), ("expires_at", 1)], name="archives_by_status_expiry")
        await self.db[ARCHIVES].create_index("participant_user_ids", name="archives_by_user")
        await self.db[RECORDINGS].create_index([("room_id", 1), ("created_at", -1)], name="recordings_by_room")
        await self.db[RECORDINGS].create_index("status", name="recordings_by_status")
        # Database-level guarantee: at most one active recording per room.
        await self.db[RECORDINGS].create_index(
            "room_id",
            unique=True,
            name="uniq_active_recording_per_room",
            partialFilterExpression={"active": True},
        )

    # ── Settings ────────────────────────────────────────────────────────────

    async def get_retention_settings(self) -> Dict[str, Any]:
        doc = await self.db[SETTINGS].find_one({"_id": RETENTION_SETTINGS_ID}) if self.db is not None else None
        if doc and doc.get("default_retention_days"):
            return {
                "default_retention_days": int(doc["default_retention_days"]),
                "updated_at": doc.get("updated_at"),
                "updated_by": doc.get("updated_by"),
                "source": "admin",
            }
        return {
            "default_retention_days": self.default_retention_days,
            "updated_at": None,
            "updated_by": None,
            "source": "config",
        }

    async def set_default_retention_days(self, days: int, *, updated_by: str) -> Dict[str, Any]:
        days = validate_retention_days(days)
        await self.db[SETTINGS].update_one(
            {"_id": RETENTION_SETTINGS_ID},
            {"$set": {"default_retention_days": days, "updated_at": utcnow(), "updated_by": updated_by}},
            upsert=True,
        )
        return await self.get_retention_settings()

    async def managed_since(self) -> Any:
        """When this deployment started managing archives; earlier meetings are legacy."""
        await self.db[SETTINGS].update_one(
            {"_id": LIFECYCLE_SETTINGS_ID},
            {"$setOnInsert": {"managed_since": utcnow()}},
            upsert=True,
        )
        doc = await self.db[SETTINGS].find_one({"_id": LIFECYCLE_SETTINGS_ID})
        return as_utc((doc or {}).get("managed_since")) or utcnow()

    # ── Archives ────────────────────────────────────────────────────────────

    async def ensure_archive(self, room_id: str, *, room_languages: Optional[List[str]] = None) -> Dict[str, Any]:
        """Creates the archive record on first need, snapshotting the current default retention."""
        archive_id = archive_id_for_room(room_id)
        existing = await self.get_archive_by_room(room_id)
        if existing:
            return existing
        retention = await self.get_retention_settings()
        now = utcnow()
        await self.db[ARCHIVES].update_one(
            {"room_id": room_id},
            {
                "$setOnInsert": {
                    "_id": archive_id,
                    "archive_id": archive_id,
                    "room_id": room_id,
                    "status": ARCHIVE_OPEN,
                    "default_retention_days_snapshot": retention["default_retention_days"],
                    "retention_override_days": None,
                    "expires_at": None,
                    "ended_at": None,
                    "created_at": now,
                    "finalized_at": None,
                    "deleted_at": None,
                    "room_languages": room_languages or [],
                    "participant_user_ids": [],
                    "files": {},
                    "attempts": 0,
                },
                "$set": {"updated_at": now},
            },
            upsert=True,
        )
        return await self.get_archive_by_room(room_id)

    async def get_archive_by_room(self, room_id: str) -> Optional[Dict[str, Any]]:
        return await self.db[ARCHIVES].find_one({"room_id": room_id})

    async def get_archive(self, archive_id: str) -> Optional[Dict[str, Any]]:
        return await self.db[ARCHIVES].find_one({"_id": archive_id})

    async def update_archive(self, archive_id: str, fields: Dict[str, Any], *, unset: Iterable[str] = ()) -> Dict[str, Any]:
        update: Dict[str, Any] = {"$set": {**fields, "updated_at": utcnow()}}
        unset = list(unset)
        if unset:
            update["$unset"] = {key: "" for key in unset}
        await self.db[ARCHIVES].update_one({"_id": archive_id}, update)
        archive = await self.get_archive(archive_id)
        if archive is not None and ("expires_at" in fields or "status" in fields):
            # Mirrored on the room so My meetings and search hide expired content even
            # before the cleanup worker has deleted it (no ghost results).
            await self.db["rooms"].update_one(
                {"room_id": archive["room_id"]},
                {"$set": {"archive_expires_at_dt": archive.get("expires_at"), "archive_status": archive.get("status")}},
            )
        return archive

    async def set_retention(self, archive: Dict[str, Any], override_days: Optional[int]) -> Dict[str, Any]:
        if override_days is not None:
            validate_retention_days(override_days)
        candidate = {**archive, "retention_override_days": override_days}
        expires_at = compute_expires_at(candidate) if archive.get("ended_at") else None
        return await self.update_archive(
            archive["_id"],
            {"retention_override_days": override_days, "expires_at": expires_at},
        )

    async def list_archives(
        self,
        query: Dict[str, Any],
        *,
        sort: str = "created_at",
        direction: int = -1,
        skip: int = 0,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        cursor = self.db[ARCHIVES].find(query).sort(sort, direction).skip(skip).limit(limit)
        return await cursor.to_list(length=limit)

    async def count_archives(self, query: Dict[str, Any]) -> int:
        return await self.db[ARCHIVES].count_documents(query)

    # ── Recordings ──────────────────────────────────────────────────────────

    async def insert_recording(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        await self.db[RECORDINGS].insert_one(doc)
        return doc

    async def get_recording(self, recording_id: str) -> Optional[Dict[str, Any]]:
        return await self.db[RECORDINGS].find_one({"_id": recording_id})

    async def update_recording(
        self,
        recording_id: str,
        fields: Dict[str, Any],
        *,
        expected_statuses: Optional[Iterable[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Compare-and-set on status so concurrent stop/expiry/poll finalize exactly once."""
        query: Dict[str, Any] = {"_id": recording_id}
        if expected_statuses is not None:
            query["status"] = {"$in": list(expected_statuses)}
        if "status" in fields:
            fields = {**fields, "active": fields["status"] in REC_ACTIVE_STATUSES}
        result = await self.db[RECORDINGS].update_one(
            query,
            {"$set": {**fields, "updated_at": utcnow()}, "$inc": {"version": 1}},
        )
        if getattr(result, "matched_count", 1) == 0:
            return None
        return await self.get_recording(recording_id)

    async def active_recording(self, room_id: str) -> Optional[Dict[str, Any]]:
        return await self.db[RECORDINGS].find_one({"room_id": room_id, "status": {"$in": list(REC_ACTIVE_STATUSES)}})

    async def latest_recording(self, room_id: str) -> Optional[Dict[str, Any]]:
        docs = await self.db[RECORDINGS].find({"room_id": room_id}).sort("created_at", -1).limit(1).to_list(length=1)
        return docs[0] if docs else None

    async def list_recordings(self, room_id: str) -> List[Dict[str, Any]]:
        return await self.db[RECORDINGS].find({"room_id": room_id}).sort("created_at", 1).to_list(length=200)

    async def pending_recordings(self, limit: int = 100) -> List[Dict[str, Any]]:
        return await self.db[RECORDINGS].find({"status": {"$in": list(REC_PENDING_STATUSES)}}).limit(limit).to_list(length=limit)

    async def delete_room_recordings(self, room_id: str) -> int:
        result = await self.db[RECORDINGS].delete_many({"room_id": room_id})
        return int(getattr(result, "deleted_count", 0) or 0)
